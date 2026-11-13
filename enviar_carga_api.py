import argparse
import csv
import gzip
import io
import json
from pathlib import Path
from urllib.request import Request, urlopen

from openpyxl import load_workbook


ATIVOS = ("CO", "ES", "MG", "NE", "NO", "PR", "RJ", "RS", "SC", "SP")


def ler_lote(pasta):
    linhas = []
    for ativo in ATIVOS:
        arquivo = pasta / f"chamados {ativo}.xlsx"
        livro = load_workbook(arquivo, read_only=True, data_only=True)
        try:
            valores = livro.active.values
            cabecalho = [next(valores) for _ in range(7)][6][:41]
            for linha in valores:
                if linha[0] is None:
                    continue
                n_os = str(linha[0]).strip()
                if not n_os.isdecimal():
                    continue
                dados = dict(zip(cabecalho[1:], linha[1:], strict=True))
                linhas.append({"ativo": ativo, "n_os": int(n_os), "dados": dados})
        finally:
            livro.close()
        print(f"{ativo}: pronto", flush=True)
    return linhas


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pasta", type=Path)
    parser.add_argument("url")
    parser.add_argument("chave")
    args = parser.parse_args()
    corpo = json.dumps({"rows": ler_lote(args.pasta)}, ensure_ascii=False, default=str).encode("utf-8")
    comprimido = gzip.compress(corpo)
    requisicao = Request(args.url.rstrip("/") + "/carga", data=comprimido, method="POST")
    requisicao.add_header("Content-Type", "application/json")
    requisicao.add_header("Content-Encoding", "gzip")
    requisicao.add_header("X-API-Key", args.chave)
    with urlopen(requisicao, timeout=600) as resposta:
        print(resposta.read().decode("utf-8"), flush=True)


if __name__ == "__main__":
    main()
