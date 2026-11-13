import argparse
import csv
import getpass
import json
import os
from pathlib import Path
import subprocess
import tempfile

from openpyxl import load_workbook


ATIVOS = ("CO", "ES", "MG", "NE", "NO", "PR", "RJ", "RS", "SC", "SP")
PSQL = r"C:\Program Files\PostgreSQL\18\bin\psql.exe"


def escrever_lote(pasta, saida):
    saida.write("LOCK TABLE public.chamados IN SHARE ROW EXCLUSIVE MODE;\n")
    saida.write("DELETE FROM public.chamados;\n")
    saida.write("COPY public.chamados (ativo, n_os, dados) FROM STDIN WITH (FORMAT csv);\n")
    csv_saida = csv.writer(saida, lineterminator="\n")
    cabecalho_lote = None
    for ativo in ATIVOS:
        arquivo = pasta / f"chamados {ativo}.xlsx"
        planilha = load_workbook(arquivo, read_only=True, data_only=True)
        try:
            linhas = planilha.active.values
            primeiras = [next(linhas) for _ in range(7)]
            if str(primeiras[2][0]).strip() != f"Ativo {ativo}":
                raise ValueError(f"{arquivo.name}: ativo inesperado")
            cabecalho = tuple(primeiras[6][:41])
            if (
                len(cabecalho) != 41
                or cabecalho[0] != "N_OS"
                or any(not isinstance(nome, str) or not nome.strip() for nome in cabecalho)
                or len(set(cabecalho)) != 41
                or (cabecalho_lote is not None and cabecalho != cabecalho_lote)
            ):
                raise ValueError(f"{arquivo.name}: cabeçalho inesperado")
            cabecalho_lote = cabecalho
            quantidade = 0
            for numero_linha, linha in enumerate(linhas, 8):
                valores = linha[:41]
                if all(valor is None for valor in valores):
                    continue
                numero = str(valores[0]).strip()
                if not numero.isdecimal():
                    raise ValueError(f"{arquivo.name}: N_OS inválido na linha {numero_linha}")
                dados = dict(zip(cabecalho[1:], valores[1:], strict=True))
                csv_saida.writerow((ativo, int(numero), json.dumps(dados, ensure_ascii=False, default=str)))
                quantidade += 1
            if not quantidade:
                raise ValueError(f"{arquivo.name}: relatório sem chamados")
            print(f"{ativo}: {quantidade:,} chamados", flush=True)
        finally:
            planilha.close()
    saida.write("\\.\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pasta", type=Path)
    parser.add_argument("--gravar", action="store_true")
    parser.add_argument("--porta", default="5432")
    parser.add_argument("--usuario", default="postgres")
    parser.add_argument("--banco", default="chamados_telefonica_teste")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temporario:
        lote = Path(temporario) / "lote.sql"
        with lote.open("w", encoding="utf-8", newline="") as saida:
            escrever_lote(args.pasta, saida)
        if args.gravar:
            senha = getpass.getpass("Senha do PostgreSQL: ")
            subprocess.run(
                [PSQL, "-X", "-w", "-h", "127.0.0.1", "-p", args.porta,
                 "-U", args.usuario, "-d", args.banco, "-v", "ON_ERROR_STOP=1",
                 "--single-transaction", "-f", str(lote)],
                env={**os.environ, "PGPASSWORD": senha, "PGCLIENTENCODING": "UTF8"},
                check=True,
            )


if __name__ == "__main__":
    main()
