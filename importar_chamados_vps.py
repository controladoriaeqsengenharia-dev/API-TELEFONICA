import argparse
import csv
import getpass
import io
import json
from pathlib import Path

import psycopg
from openpyxl import load_workbook


ATIVOS = ("CO", "ES", "MG", "NE", "NO", "PR", "RJ", "RS", "SC", "SP")


def gerar_csv(pasta):
    arquivo_csv = io.StringIO(newline="")
    writer = csv.writer(arquivo_csv, lineterminator="\n")
    for ativo in ATIVOS:
        arquivo = pasta / f"chamados {ativo}.xlsx"
        livro = load_workbook(arquivo, read_only=True, data_only=True)
        try:
            linhas = livro.active.values
            cabecalho = [next(linhas) for _ in range(7)][6][:41]
            if cabecalho[0] != "N_OS" or len(set(cabecalho)) != 41:
                raise ValueError(f"Cabeçalho inválido em {arquivo.name}")
            quantidade = 0
            for linha in linhas:
                valores = linha[:41]
                if valores[0] is None:
                    continue
                numero = str(valores[0]).strip()
                if not numero.isdecimal():
                    continue
                dados = dict(zip(cabecalho[1:], valores[1:], strict=True))
                writer.writerow((ativo, int(numero), json.dumps(dados, ensure_ascii=False, default=str)))
                quantidade += 1
            print(f"{ativo}: {quantidade:,} chamados", flush=True)
        finally:
            livro.close()
    arquivo_csv.seek(0)
    return arquivo_csv


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pasta", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--porta", default=15432, type=int)
    parser.add_argument("--usuario", default="telefonica_carga")
    parser.add_argument("--banco", default="chamados_telefonica")
    args = parser.parse_args()
    senha = getpass.getpass("Senha do PostgreSQL na VPS: ")
    dados_csv = gerar_csv(args.pasta)
    with psycopg.connect(host=args.host, port=args.porta, user=args.usuario,
                         password=senha, dbname=args.banco) as conexao:
        with conexao.transaction():
            with conexao.cursor() as cursor:
                cursor.execute("LOCK TABLE public.chamados IN SHARE ROW EXCLUSIVE MODE")
                cursor.execute("DELETE FROM public.chamados")
                with cursor.copy("COPY public.chamados (ativo, n_os, dados) FROM STDIN WITH (FORMAT csv)") as copia:
                    copia.write(dados_csv.getvalue())
        print("Carga concluída.", flush=True)


if __name__ == "__main__":
    main()
