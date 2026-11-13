import argparse
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen

from openpyxl import Workbook, load_workbook


ATIVOS = ("CO", "ES", "MG", "NE", "NO", "PR", "RJ", "RS", "SC", "SP")
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


def consolidar_relatorios(pasta):
    with TemporaryDirectory(dir=pasta) as temporaria:
        for grupo, nome, aba in CONSOLIDADOS:
            livro = Workbook(write_only=True)
            planilha = livro.create_sheet(aba)
            cabecalho = None
            for ativo in ATIVOS:
                if (ativo == "SP") != (grupo == "SP"):
                    continue
                with_rows = ler_relatorio(pasta / f"chamados {ativo}.xlsx", inicio=7)
                try:
                    colunas = next(with_rows)
                    if cabecalho is None:
                        cabecalho = colunas
                        planilha.append(colunas)
                    elif colunas != cabecalho:
                        raise ValueError(f"Cabeçalho divergente: {ativo}")
                    for linha in with_rows:
                        planilha.append(linha)
                finally:
                    with_rows.close()
            livro.save(Path(temporaria) / nome)
        for _, nome, _ in CONSOLIDADOS:
            (Path(temporaria) / nome).replace(pasta / nome)


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
    print(enviar_carga(args.pasta, args.url, args.chave), flush=True)


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
