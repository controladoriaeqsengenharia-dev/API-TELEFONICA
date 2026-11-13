import gzip
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psycopg


DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    DATABASE_URL = {
        "host": os.getenv("PGHOST", "127.0.0.1"),
        "port": os.getenv("PGPORT", "5432"),
        "dbname": os.environ["PGDATABASE"],
        "user": os.environ["PGUSER"],
        "password": os.environ["PGPASSWORD"],
    }
API_KEY = os.environ["API_KEY"]
MAX_BODY = 250 * 1024 * 1024


def normalize(status):
    return status.replace("Pendente Aprovação Gerente Nacional", "Concluida").replace(
        "Pendente Aprovação Gerente Regional", "Concluida"
    )


class Handler(BaseHTTPRequestHandler):
    def authorized(self):
        return self.headers.get("X-API-Key") == API_KEY

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/carga" or not self.authorized():
            self.send_json(404, {"erro": "não encontrado"})
            return
        tamanho = int(self.headers.get("Content-Length", "0"))
        if tamanho <= 0 or tamanho > MAX_BODY:
            self.send_json(413, {"erro": "carga inválida"})
            return
        corpo = self.rfile.read(tamanho)
        if self.headers.get("Content-Encoding") == "gzip":
            corpo = gzip.decompress(corpo)
        lote = json.loads(corpo)
        linhas = lote["rows"]
        if not linhas:
            self.send_json(400, {"erro": "lote vazio"})
            return
        with psycopg.connect(DATABASE_URL) as conexao:
            with conexao.transaction():
                with conexao.cursor() as cursor:
                    cursor.execute("LOCK TABLE public.chamados IN SHARE ROW EXCLUSIVE MODE")
                    cursor.execute("DELETE FROM public.chamados")
                    cursor.executemany(
                        "INSERT INTO public.chamados (ativo, n_os, dados) VALUES (%s, %s, %s)",
                        ((linha["ativo"], linha["n_os"], json.dumps(linha["dados"])) for linha in linhas),
                    )
        self.send_json(200, {"linhas": len(linhas)})

    def do_GET(self):
        if not self.authorized():
            self.send_json(404, {"erro": "não encontrado"})
            return
        if self.path == "/telefonica-sp":
            filtro = "ativo = 'SP'"
        elif self.path == "/telefonica":
            filtro = "ativo <> 'SP' AND COALESCE(dados->>'UF', '') NOT IN ('1101505', '1101507', '1101509', '2100101B', '85009S0', 'EGS')"
        else:
            self.send_json(404, {"erro": "não encontrado"})
            return
        with psycopg.connect(DATABASE_URL) as conexao:
            with conexao.cursor() as cursor:
                cursor.execute(f"SELECT n_os, dados FROM public.chamados WHERE {filtro}")
                resultado = []
                for n_os, dados in cursor:
                    dados["N_OS"] = n_os
                    dados["Denominacao_Estado_OS"] = normalize(dados.get("Denominacao_Estado_OS", ""))
                    resultado.append(dados)
        self.send_json(200, resultado)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(os.getenv("PORT", "8001"))), Handler).serve_forever()
