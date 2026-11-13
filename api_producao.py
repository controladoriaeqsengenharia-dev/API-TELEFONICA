import gzip
from hmac import compare_digest
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import psycopg


DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    DATABASE_CONNECTION = DATABASE_URL
else:
    DATABASE_CONNECTION = {
        "host": os.getenv("PGHOST", "127.0.0.1"),
        "port": os.getenv("PGPORT", "5432"),
        "dbname": os.environ["PGDATABASE"],
        "user": os.environ["PGUSER"],
        "password": os.environ["PGPASSWORD"],
    }
API_KEY = os.environ["API_KEY"]
READ_API_KEY = os.getenv("READ_API_KEY")
MAX_BODY = 250 * 1024 * 1024

SWAGGER_HTML = """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <title>API Telefonica - Swagger</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.onload = () => SwaggerUIBundle({
      url: '/openapi.json',
      dom_id: '#swagger-ui',
      persistAuthorization: true
    });
  </script>
</body>
</html>"""


OPENAPI = {
    "openapi": "3.0.3",
    "info": {
        "title": "API Telefonica",
        "description": "Consulta e carga dos chamados Telefonica.",
        "version": "1.0.0",
    },
    "servers": [{"url": "/"}],
    "components": {
        "parameters": {
            "Limit": {
                "name": "limit",
                "in": "query",
                "description": "Máximo de registros. Omita para receber a carga completa.",
                "schema": {"type": "integer", "minimum": 1, "maximum": 1000},
                "example": 10,
            }
        },
        "securitySchemes": {
            "ApiKeyAuth": {
                "type": "apiKey",
                "in": "header",
                "name": "X-API-Key",
            }
        },
        "schemas": {
            "Chamado": {
                "type": "object",
                "additionalProperties": True,
                "description": "Chamado com as colunas do relatório.",
            },
            "Carga": {
                "type": "object",
                "required": ["rows"],
                "properties": {
                    "rows": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["ativo", "n_os", "dados"],
                            "properties": {
                                "ativo": {"type": "string", "example": "MG"},
                                "n_os": {"type": "integer", "example": 123456},
                                "dados": {"$ref": "#/components/schemas/Chamado"},
                            },
                        },
                    }
                },
            },
        },
    },
    "paths": {
        "/telefonica": {
            "get": {
                "summary": "Lista chamados gerais",
                "parameters": [{"$ref": "#/components/parameters/Limit"}],
                "security": [{"ApiKeyAuth": []}],
                "responses": {"200": {"description": "Lista de chamados"}},
            }
        },
        "/telefonica-sp": {
            "get": {
                "summary": "Lista chamados de São Paulo",
                "parameters": [{"$ref": "#/components/parameters/Limit"}],
                "security": [{"ApiKeyAuth": []}],
                "responses": {"200": {"description": "Lista de chamados SP"}},
            }
        },
        "/carga": {
            "post": {
                "summary": "Substitui a carga inteira",
                "security": [{"ApiKeyAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Carga"}
                        }
                    },
                },
                "responses": {"200": {"description": "Carga concluída"}},
            }
        },
    },
}


def open_database():
    if isinstance(DATABASE_CONNECTION, str):
        return psycopg.connect(DATABASE_CONNECTION)
    return psycopg.connect(**DATABASE_CONNECTION)


def normalize(status):
    return status.replace("Pendente Aprovação Gerente Nacional", "Concluida").replace(
        "Pendente Aprovação Gerente Regional", "Concluida"
    )


class Handler(BaseHTTPRequestHandler):
    def authorized(self, *, leitura=False):
        chave = self.headers.get("X-API-Key", "").encode()
        esperada = READ_API_KEY if leitura and READ_API_KEY else API_KEY
        return compare_digest(chave, esperada.encode())

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
        with open_database() as conexao:
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
        if self.path == "/docs":
            body = SWAGGER_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/openapi.json":
            self.send_json(200, OPENAPI)
            return
        if not self.authorized(leitura=True):
            self.send_json(404, {"erro": "não encontrado"})
            return
        url = urlsplit(self.path)
        if url.path == "/telefonica-sp":
            filtro = "ativo = 'SP'"
        elif url.path == "/telefonica":
            filtro = "ativo <> 'SP' AND COALESCE(dados->>'UF', '') NOT IN ('1101505', '1101507', '1101509', '2100101B', '85009S0', 'EGS')"
        else:
            self.send_json(404, {"erro": "não encontrado"})
            return
        query = f"SELECT n_os, dados FROM public.chamados WHERE {filtro}"
        params = ()
        limits = parse_qs(url.query, keep_blank_values=True).get("limit")
        if limits is not None:
            try:
                limit = int(limits[0])
            except ValueError:
                limit = 0
            if len(limits) != 1 or not 1 <= limit <= 1000:
                self.send_json(400, {"erro": "limit deve ser um inteiro de 1 a 1000"})
                return
            query += " LIMIT %s"
            params = (limit,)
        with open_database() as conexao:
            with conexao.cursor() as cursor:
                cursor.execute(query, params)
                resultado = []
                for n_os, dados in cursor:
                    dados["N_OS"] = n_os
                    dados["Denominacao_Estado_OS"] = normalize(dados.get("Denominacao_Estado_OS", ""))
                    resultado.append(dados)
        self.send_json(200, resultado)


if __name__ == "__main__":
    ThreadingHTTPServer((os.getenv("BIND_HOST", "127.0.0.1"), int(os.getenv("PORT", "8001"))), Handler).serve_forever()
