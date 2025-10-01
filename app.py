# app.py
import os
import json
import requests
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from dotenv import load_dotenv
import pandas as pd
from datetime import datetime

# --------------------------
# Carregar .env
# --------------------------
load_dotenv()
TOKEN = os.getenv("TOKEN_API")
HOST = os.getenv("HOST_API")

if not TOKEN or not HOST:
    raise RuntimeError("Variáveis TOKEN_API e HOST_API devem estar definidas no .env")

# --------------------------
# Inicialização Flask + CORS
# --------------------------
app = Flask(__name__)
# Habilita CORS para dev local (em produção restrinja origins)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# Cabeçalhos básicos (Authorization + Content-Type)
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": TOKEN
}

# --------------------------
# Helpers
# --------------------------
def add_cors_response(resp):
    """Garante headers CORS para respostas geradas manualmente."""
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization,ixcsoft"
    return resp

@app.before_request
def handle_options_preflight():
    """Responde rapidamente OPTIONS preflight para qualquer rota."""
    if request.method == "OPTIONS":
        resp = make_response()
        return add_cors_response(resp)

def consultar_ixc_registro(endpoint, payload, listar=True):
    """
    Faz POST para {HOST}/{endpoint} com header ixcsoft:listar (quando listar=True)
    Retorna (registro_unico, None) em sucesso, ou (None, mensagem_erro) em erro.
    """
    url = f"{HOST}/{endpoint}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": TOKEN
    }
    if listar:
        headers["ixcsoft"] = "listar"
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
    except Exception as e:
        return None, f"Erro conexão IXC {endpoint}: {str(e)}"

    # tentar parsear JSON
    try:
        data = resp.json()
    except Exception:
        return None, f"Erro ao ler resposta IXC {endpoint}: status {resp.status_code} - {resp.text}"

    # verifica total
    try:
        total = int(data.get("total", 0))
    except Exception:
        total = 0

    if total == 0:
        return None, f"Nenhum registro encontrado em {endpoint}."
    return data["registros"][0], None

def get_login_id(id_contrato):
    payload = {
        "qtype": "id_contrato",
        "query": str(id_contrato),
        "oper": "=",
        "page": "1",
        "rp": "1"
    }
    registro, err = consultar_ixc_registro("radusuarios", payload, listar=True)
    if err:
        return None, err
    return registro.get("id"), None

def format_date_br_with_time(date_iso, period):
    """Converte 'YYYY-MM-DD' para 'DD/MM/YYYY HH:MM:SS' com base no periodo."""
    if not date_iso:
        return ""
    try:
        date_part = date_iso.split("T")[0]
        dt = datetime.strptime(date_part, "%Y-%m-%d")
        hour = {
            "comercial": "10:00:00",
            "manha": "09:00:00",
            "tarde": "14:00:00"
        }.get(period, "10:00:00")
        return dt.strftime("%d/%m/%Y") + " " + hour
    except Exception:
        return date_iso

# --------------------------
# Rotas de consulta (frontend precisa delas)
# --------------------------
@app.route("/api/cliente", methods=["POST", "OPTIONS"])
def rota_cliente_lookup():
    try:
        payload = request.get_json() or {}
        client_id = payload.get("clientId") or payload.get("query") or payload.get("id_cliente")
        if not client_id:
            return add_cors_response(jsonify({"error": "ID do cliente é obrigatório."})), 400

        q = {
            "qtype": "id",
            "query": str(client_id),
            "oper": "=",
            "page": "1",
            "rp": "1"
        }
        registro, err = consultar_ixc_registro("cliente", q, listar=True)
        if err:
            return add_cors_response(jsonify({"error": err})), 400
        return add_cors_response(jsonify(registro)), 200
    except Exception as e:
        return add_cors_response(jsonify({"error": str(e)})), 500

@app.route("/api/cliente_contrato", methods=["POST", "OPTIONS"])
def rota_contrato_lookup():
    try:
        payload = request.get_json() or {}
        contract_id = payload.get("contractId") or payload.get("query") or payload.get("id_contrato")
        if not contract_id:
            return add_cors_response(jsonify({"error": "ID do contrato é obrigatório."})), 400

        q = {
            "qtype": "id",
            "query": str(contract_id),
            "oper": "=",
            "page": "1",
            "rp": "1"
        }
        registro, err = consultar_ixc_registro("cliente_contrato", q, listar=True)
        if err:
            return add_cors_response(jsonify({"error": err})), 400
        return add_cors_response(jsonify(registro)), 200
    except Exception as e:
        return add_cors_response(jsonify({"error": str(e)})), 500

# --------------------------
# Rota principal: transfer (segue lógica do Jupyter)
# --------------------------
@app.route("/api/transfer", methods=["POST", "OPTIONS"])
def rota_transfer():
    try:
        data = request.get_json() or {}

        # ids obrigatórios
        id_cliente = data.get("clientId") or data.get("id_cliente")
        id_contrato = data.get("contractId") or data.get("id_contrato")
        if not id_cliente or not id_contrato:
            return add_cors_response(jsonify({"error": "ID do cliente e contrato são obrigatórios."})), 400

        # campos
        id_tecnico = data.get("id_tecnico") or "147"
        nome_cliente = data.get("nome_cliente") or ""
        telefone = data.get("telefone") or ""
        valueType = data.get("valueType") or data.get("valor") or ""
        valor = data.get("taxValue") if valueType == "taxa" else ("Renovação" if valueType == "renovacao" else "")
        scheduledDate = data.get("scheduledDate")  # YYYY-MM-DD
        period = data.get("period") or data.get("periodo") or ""
        data_str = format_date_br_with_time(scheduledDate, period)

        endereco = data.get("address") or data.get("endereco") or ""
        numero = data.get("number") or data.get("numero") or ""
        bairro = data.get("neighborhood") or data.get("bairro") or ""
        cep = data.get("cep") or ""
        cidade = data.get("city") or data.get("cidade") or ""

        endereco_antigo = data.get("oldAddress") or data.get("endereco_antigo") or ""
        numero_antigo = data.get("oldNumber") or data.get("old_numero") or ""
        bairro_antigo = data.get("oldNeighborhood") or data.get("old_bairro") or ""
        cep_antigo = data.get("oldCep") or ""
        cidade_antiga = data.get("oldCity") or ""

        des_porta = data.get("portaNumber") or data.get("des_porta") or ""

        # 1) obter id_login
        id_login, err_login = get_login_id(id_contrato)
        if err_login:
            return add_cors_response(jsonify({"error": err_login})), 400

        # 2) criar ticket de transferência
        mensagem = f"""\n
Quem receberá: {nome_cliente}
Contato: {telefone}
Títular/Responsável Legal: {nome_cliente}
Valor: {valor}
Data/Período: {data_str} - {period}
*Qualquer valor referente ao serviço deverá ser pago no momento da visita técnica, cliente ciente.

Cliente solicita transferência de endereço.
Endereço atual/Desativação de porta: {endereco_antigo}, {numero_antigo} - {bairro_antigo} / {des_porta}
Novo endereço: {endereco}, {numero} - {bairro}, {cep}
""".strip()

        payload_ticket = {
            "tipo": "C",
            "id_cliente": id_cliente,
            "id_login": id_login,
            "id_contrato": id_contrato,
            "id_assunto": "80",
            "menssagem": mensagem,
            "origem_endereco": "CC",
            "id_responsavel_tecnico": id_tecnico,
            "titulo": "Transferência de endereço",
            "su_status": "AG",
            "id_ticket_setor": "3",
            "prioridade": "M",
            "id_wfl_processo": "8",
            "setor": "3"
        }

        print("DEBUG: payload_ticket:", json.dumps(payload_ticket, ensure_ascii=False))
        resp_ticket = requests.post(f"{HOST}/su_ticket", headers=HEADERS, data=json.dumps(payload_ticket), timeout=30)
        print("DEBUG: resp_ticket.status_code:", resp_ticket.status_code)
        print("DEBUG: resp_ticket.text:", resp_ticket.text)
        if resp_ticket.status_code != 200:
            return add_cors_response(jsonify({"error": f"Erro ao criar ticket: {resp_ticket.status_code} - {resp_ticket.text}"})), 400
        ticket_data = resp_ticket.json()
        id_ticket = ticket_data.get("id")

        # 3) buscar OS do ticket
        payload_busca_os = {
            "qtype": "id_ticket",
            "query": id_ticket,
            "oper": "=",
            "page": "1",
            "rp": "1"
        }
        headers_listar = {**HEADERS, "ixcsoft": "listar"}
        resp_os_busca = requests.post(f"{HOST}/su_oss_chamado", headers=headers_listar, data=json.dumps(payload_busca_os), timeout=30)
        print("DEBUG: resp_os_busca.status_code:", resp_os_busca.status_code)
        print("DEBUG: resp_os_busca.text:", resp_os_busca.text)
        os_data = resp_os_busca.json()
        if str(os_data.get("total", 0)) == "0":
            return add_cors_response(jsonify({"error": "Nenhuma OS encontrada para o ticket criado."})), 400
        id_os = os_data["registros"][0]["id"]
        mensagem_atual = os_data["registros"][0].get("mensagem") or mensagem

        # 4) agendar OS de transferência (PUT)
        payload_agenda = {
            "tipo": "C",
            "id": id_os,
            "id_cliente": id_cliente,
            "id_login": id_login,
            "id_contrato_kit": id_contrato,
            "id_tecnico": id_tecnico,
            "melhor_horario_agenda": "Q",
            "status": "AG",
            "id_filial": 2,
            "id_assunto": 258,
            "setor": 1,
            "prioridade": "N",
            "origem_endereco": "CC",
            "mensagem_resposta": "Agendado via API - Marques",
            "endereco": endereco,
            "numero": numero,
            "bairro": bairro,
            "cep": cep,
            "cidade": cidade,
            "data_agenda": data_str,
            "data_agenda_final": data_str,
            "mensagem": mensagem_atual
        }
        print("DEBUG: payload_agenda (transfer):", json.dumps(payload_agenda, ensure_ascii=False))
        resp_put = requests.put(f"{HOST}/su_oss_chamado/{id_os}", headers=HEADERS, data=json.dumps(payload_agenda), timeout=30)
        print("DEBUG: resp_put.status_code:", resp_put.status_code)
        print("DEBUG: resp_put.text:", resp_put.text)
        if resp_put.status_code != 200:
            return add_cors_response(jsonify({"error": f"Erro ao agendar OS: {resp_put.status_code} - {resp_put.text}"})), 400

        # 5) gerar protocolo e criar OS de desativação
        resp_proto = requests.post(f"{HOST}/gerar_protocolo_atendimento", headers={**HEADERS, "ixcsoft": "inserir"}, timeout=30)
        protocolo = resp_proto.text
        print("DEBUG: protocolo gerado:", protocolo)

        mensagem_des = f"\nDesativar porta: {des_porta}\nCliente mudando para {endereco}, {numero} - {bairro}, {cep}"
        payload_des = {
            "tipo": "C",
            "protocolo": protocolo,
            "id_cliente": id_cliente,
            "id_login": id_login,
            "id_contrato_kit": id_contrato,
            "mensagem": mensagem_des,
            "id_responsavel_tecnico": id_tecnico,
            "data_agenda": data_str,
            "data_agenda_final": data_str,
            "id_tecnico": id_tecnico,
            "endereco": endereco_antigo,
            "numero": numero_antigo,
            "bairro": bairro_antigo,
            "cep": cep_antigo,
            "cidade": cidade_antiga,
            "origem_endereco": "M",
            "id_assunto": "17",
            "titulo": "Desativação de porta",
            "status": "AG",
            "prioridade": "N",
            "setor": "1",
            "id_filial": "2"
        }
        print("DEBUG: payload_des:", json.dumps(payload_des, ensure_ascii=False))
        resp_des = requests.post(f"{HOST}/su_oss_chamado", headers=HEADERS, data=json.dumps(payload_des), timeout=30)
        print("DEBUG: resp_des.status_code:", resp_des.status_code)
        print("DEBUG: resp_des.text:", resp_des.text)
        if resp_des.status_code != 200:
            return add_cors_response(jsonify({"error": f"Erro ao criar OS desativação: {resp_des.status_code} - {resp_des.text}"})), 400

        # 6) atualizar contrato (buscar + PUT) - replicando Jupyter
        payload_get = {
            "qtype": "id",
            "query": str(id_contrato),
            "oper": "=",
            "page": "1",
            "rp": "1"
        }
        headers_listar = {**HEADERS, "ixcsoft": "listar"}
        res_contrato = requests.post(f"{HOST}/cliente_contrato", headers=headers_listar, data=json.dumps(payload_get), timeout=30)
        print("DEBUG: res_contrato.status:", res_contrato.status_code)
        print("DEBUG: res_contrato.text:", res_contrato.text)
        contrato_data = res_contrato.json()
        if "registros" not in contrato_data or len(contrato_data["registros"]) == 0:
            return add_cors_response(jsonify({"error": "Contrato não encontrado"})), 400

        registro = contrato_data["registros"][0]

        registro["endereco"] = endereco
        registro["numero"] = numero
        registro["bairro"] = bairro
        registro["cep"] = cep
        registro["cidade"] = cidade

        # converte datas (igual Jupyter)
        def try_format(field, fmt="%d/%m/%Y"):
            if field in registro and registro[field]:
                try:
                    return pd.to_datetime(registro[field]).strftime(fmt)
                except Exception:
                    return registro[field]
            return registro.get(field, "")

        registro["data"] = try_format("data", "%d/%m/%Y")
        registro["data_expiracao"] = try_format("data_expiracao", "%d/%m/%Y")
        registro["data_ativacao"] = try_format("data_ativacao", "%d/%m/%Y")
        registro["data_renovacao"] = try_format("data_renovacao", "%d/%m/%Y")
        registro["data_cadastro_sistema"] = try_format("data_cadastro_sistema", "%d/%m/%Y %H:%M:%S")

        registro["endereco_padrao_cliente"] = "N"
        registro["motivo_cancelamento"] = registro.get("motivo_cancelamento", " ")

        # remove campos problemáticos
        if "ultima_atualizacao" in registro:
            registro.pop("ultima_atualizacao", None)

        url_put = f"{HOST}/cliente_contrato/{id_contrato}"
        headers_put_endereco = {
            "Content-Type": "application/json",
            "Authorization": TOKEN
        }
        print("DEBUG: PUT payload (trim):", json.dumps({
            "endereco": registro.get("endereco"),
            "numero": registro.get("numero"),
            "bairro": registro.get("bairro"),
            "cep": registro.get("cep"),
            "cidade": registro.get("cidade")
        }, ensure_ascii=False))

        res_put_endereco = requests.put(url_put, headers=headers_put_endereco, data=json.dumps(registro), timeout=30)
        print("DEBUG: res_put_endereco.status:", res_put_endereco.status_code)
        print("DEBUG: res_put_endereco.text:", res_put_endereco.text)

        # se a IXC exigir motivo do cancelamento, ela responde no texto; devolvemos ao frontend
        if res_put_endereco.status_code != 200:
            return add_cors_response(jsonify({"error": f"Erro ao atualizar contrato: {res_put_endereco.status_code} - {res_put_endereco.text}"})), 400

        # sucesso
        return add_cors_response(jsonify({
            "message": "Transferência, desativação e atualização do endereço realizadas com sucesso!",
            "id_ticket": id_ticket,
            "id_os_transferencia": id_os,
            "id_os_desativacao": resp_des.json().get("id")
        })), 200

    except Exception as e:
        print("EXCEPTION:", str(e))
        return add_cors_response(jsonify({"error": str(e)})), 500

# --------------------------
# Endpoint dedicado para atualizar contrato (separado)
# --------------------------
@app.route("/api/update_contrato", methods=["POST", "OPTIONS"])
def rota_update_contrato():
    try:
        data = request.get_json() or {}
        id_contrato = data.get("contractId") or data.get("id_contrato")
        if not id_contrato:
            return add_cors_response(jsonify({"error": "ID do contrato (contractId) é obrigatório."})), 400

        endereco = data.get("address") or data.get("endereco") or ""
        numero = data.get("number") or data.get("numero") or ""
        bairro = data.get("neighborhood") or data.get("bairro") or ""
        cep = data.get("cep") or ""
        cidade = data.get("city") or data.get("cidade") or ""
        motivo_cancelamento = data.get("motivo_cancelamento", " ")

        payload_get = {
            "qtype": "id",
            "query": str(id_contrato),
            "oper": "=",
            "page": "1",
            "rp": "1"
        }
        headers_listar = {**HEADERS, "ixcsoft": "listar"}
        res = requests.post(f"{HOST}/cliente_contrato", headers=headers_listar, data=json.dumps(payload_get), timeout=30)
        print("DEBUG update_contrato: GET /cliente_contrato status:", res.status_code)
        print("DEBUG update_contrato: GET body:", res.text)

        contrato_data = res.json()
        if "registros" not in contrato_data or len(contrato_data["registros"]) == 0:
            return add_cors_response(jsonify({"error": "Contrato não encontrado"})), 400

        registro = contrato_data["registros"][0]
        registro["endereco"] = endereco
        registro["numero"] = numero
        registro["bairro"] = bairro
        registro["cep"] = cep
        registro["cidade"] = cidade

        def try_format(field, fmt="%d/%m/%Y"):
            if field in registro and registro[field]:
                try:
                    return pd.to_datetime(registro[field]).strftime(fmt)
                except Exception:
                    return registro[field]
            return registro.get(field, "")

        registro["data"] = try_format("data", "%d/%m/%Y")
        registro["data_expiracao"] = try_format("data_expiracao", "%d/%m/%Y")
        registro["data_ativacao"] = try_format("data_ativacao", "%d/%m/%Y")
        registro["data_renovacao"] = try_format("data_renovacao", "%d/%m/%Y")
        registro["data_cadastro_sistema"] = try_format("data_cadastro_sistema", "%d/%m/%Y %H:%M:%S")

        registro["endereco_padrao_cliente"] = "N"
        registro["motivo_cancelamento"] = motivo_cancelamento
        if "ultima_atualizacao" in registro:
            registro.pop("ultima_atualizacao", None)

        print("DEBUG update_contrato: PUT payload trimmed:", json.dumps({
            "endereco": registro.get("endereco"),
            "numero": registro.get("numero"),
            "bairro": registro.get("bairro"),
            "cep": registro.get("cep"),
            "cidade": registro.get("cidade"),
            "motivo_cancelamento": registro.get("motivo_cancelamento")
        }, ensure_ascii=False))

        url_put = f"{HOST}/cliente_contrato/{id_contrato}"
        headers_put = {
            "Content-Type": "application/json",
            "Authorization": TOKEN
        }
        res_put = requests.put(url_put, headers=headers_put, data=json.dumps(registro), timeout=30)
        print("DEBUG update_contrato: PUT status:", res_put.status_code)
        print("DEBUG update_contrato: PUT body:", res_put.text)

        if res_put.status_code != 200:
            return add_cors_response(jsonify({"error": f"Erro ao atualizar contrato: {res_put.status_code} - {res_put.text}"})), 400

        confirm_res = requests.post(f"{HOST}/cliente_contrato", headers={**HEADERS, "ixcsoft": "listar"}, data=json.dumps(payload_get), timeout=30)
        print("DEBUG update_contrato: CONFIRM status:", confirm_res.status_code)
        print("DEBUG update_contrato: CONFIRM body:", confirm_res.text)

        return add_cors_response(jsonify({"message": "Contrato atualizado com sucesso", "put_response": res_put.json()})), 200

    except Exception as e:
        print("EXCEPTION update_contrato:", str(e))
        return add_cors_response(jsonify({"error": str(e)})), 500

# --------------------------
# Execução
# --------------------------
if __name__ == "__main__":
    # imprime variáveis pra debug (remova em produção)
    print("Running app with HOST_API:", HOST)
    app.run(host="0.0.0.0", port=5000, debug=True)
