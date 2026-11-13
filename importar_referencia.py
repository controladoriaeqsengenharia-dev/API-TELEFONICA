import csv
import getpass
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from openpyxl import load_workbook

from importar_chamados import PSQL


def preparar(arquivo, saida, sp=False):
    ativo = "SP" if sp else "REFERENCIA"
    rota = "/telefonica-sp-referencia" if sp else "/telefonica-referencia"
    saida.write(
        "CREATE TABLE IF NOT EXISTS public.chamados_referencia "
        "(LIKE public.chamados INCLUDING CONSTRAINTS);\n"
        "LOCK TABLE public.chamados_referencia IN SHARE ROW EXCLUSIVE MODE;\n"
        f"DELETE FROM public.chamados_referencia WHERE ativo = '{ativo}';\n"
        "COPY public.chamados_referencia (ativo, n_os, dados) FROM STDIN WITH (FORMAT csv);\n"
    )
    writer = csv.writer(saida, lineterminator="\n")
    livro = load_workbook(arquivo, read_only=True, data_only=True)
    try:
        linhas = livro["sisteplant" if sp else "Planilha1"].values
        colunas = next(linhas)
        if len(colunas) != 41 or colunas[0] != "N_OS" or len(set(colunas)) != 41:
            raise ValueError("Cabeçalho inesperado no Excel do SharePoint")
        for linha in linhas:
            if linha[0] is None:
                continue
            dados = dict(zip(colunas[1:], linha[1:], strict=True))
            writer.writerow((ativo, int(linha[0]), json.dumps(dados, ensure_ascii=False, default=str)))
    finally:
        livro.close()
    saida.write("\\.\n")
    from api_chamados import sql_da_rota
    saida.write("SELECT count(*) AS linhas_referencia FROM (" + sql_da_rota(rota) + ") AS resultado;\n")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as pasta:
        sql = Path(pasta) / "referencia.sql"
        with sql.open("w", encoding="utf-8", newline="") as saida:
            preparar(Path(sys.argv[1]), saida, sp="--sp" in sys.argv[2:])
        print("Excel de referência processado.", flush=True)
        if "--gravar" in sys.argv[2:]:
            senha = getpass.getpass("Senha do PostgreSQL: ")
            subprocess.run(
                [PSQL, "-X", "-w", "-h", "127.0.0.1", "-U", "postgres",
                 "-d", "chamados_telefonica_teste", "-v", "ON_ERROR_STOP=1",
                 "--single-transaction", "-f", str(sql)],
                env={**os.environ, "PGPASSWORD": senha, "PGCLIENTENCODING": "UTF8"},
                check=True,
            )
