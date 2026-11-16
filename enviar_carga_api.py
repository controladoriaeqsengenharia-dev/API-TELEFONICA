import argparse
import gzip
import json
import traceback
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

from openpyxl import load_workbook


CONSOLIDADOS = (
    ("GERAL", "CHAMADOS TELEFONICA.xlsx", "Planilha1"),
    ("SP", "TELEFONICA SP.xlsx", "sisteplant"),
)


def ler_relatorio(arquivo, aba=None, inicio=1):
    livro = load_workbook(arquivo, read_only=True, data_only=True)
    try:
        planilha = livro[aba] if aba else livro.active
        valores = planilha.iter_rows(min_row=inicio, max_col=41, values_only=True)
        colunas = next(valores)
        if colunas[0] != "N_OS" or None in colunas or len(set(colunas)) != 41:
            raise ValueError(f"Cabeçalho inválido: {arquivo.name}")
        yield colunas
        total = 0
        for linha in valores:
            if all(valor is None for valor in linha):
                continue
            if not str(linha[0]).strip().isdecimal():
                raise ValueError(f"N_OS inválido em {arquivo.name}; carga cancelada")
            total += 1
            yield linha
        if not total:
            raise ValueError(f"Relatório sem chamados: {arquivo.name}")
    finally:
        livro.close()


def ler_lote(pasta):
    linhas = []
    arquivos = [pasta / nome for _, nome, _ in CONSOLIDADOS]
    versoes = [(arquivo.stat().st_size, arquivo.stat().st_mtime_ns) for arquivo in arquivos]
    for ativo, nome, aba in CONSOLIDADOS:
        valores = ler_relatorio(pasta / nome, aba)
        try:
            colunas = next(valores)
            for linha in valores:
                dados = dict(zip(colunas[1:], linha[1:], strict=True))
                linhas.append({"ativo": ativo, "n_os": int(linha[0]), "dados": dados})
        finally:
            valores.close()
        print(f"{nome}: pronto", flush=True)
    if versoes != [(arquivo.stat().st_size, arquivo.stat().st_mtime_ns) for arquivo in arquivos]:
        raise ValueError("Os consolidados mudaram durante a leitura; aguarde o robô terminar e repita a carga")
    return linhas


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pasta", type=Path)
    parser.add_argument("url")
    parser.add_argument("chave")
    args = parser.parse_args()
    try:
        print(enviar_carga(args.pasta, args.url, args.chave), flush=True)
    except Exception:
        log = args.pasta / "ERRO_CARGA_TELEFONICA.txt"
        with log.open("a", encoding="utf-8") as arquivo:
            arquivo.write(f"\n{datetime.now().astimezone().isoformat(timespec='seconds')}\n")
            arquivo.write(traceback.format_exc())
        raise


def enviar_carga(pasta, url, chave):
    corpo = json.dumps({"rows": ler_lote(pasta)}, ensure_ascii=False, default=str).encode("utf-8")
    comprimido = gzip.compress(corpo)
    requisicao = Request(url.rstrip("/") + "/carga", data=comprimido, method="POST")
    requisicao.add_header("Content-Type", "application/json")
    requisicao.add_header("Content-Encoding", "gzip")
    requisicao.add_header("X-API-Key", chave)
    with urlopen(requisicao, timeout=600) as resposta:
        return resposta.read().decode("utf-8")


if __name__ == "__main__":
    main()
