# app.py
import os
import json
import requests
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from dotenv import load_dotenv
import pandas as pd
from datetime import datetime
import re
from urllib.parse import urlencode

# --------------------------
# Carregar .env
# --------------------------
load_dotenv()
TOKEN = os.getenv("TOKEN_API")
HOST = os.getenv("HOST_API")
GEOCODE_ENABLED = os.getenv("GEOCODE_ENABLED", "false").lower() in ("1", "true", "yes")
GEOCODE_USER_AGENT = os.getenv("GEOCODE_USER_AGENT", "my-app-geocoder/1.0")

if not TOKEN or not HOST:
    raise RuntimeError("Variáveis TOKEN_API e HOST_API devem estar definidas no .env")

# --------------------------
# Inicialização Flask + CORS
# --------------------------
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

@app.after_request
def set_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization,ixcsoft"
    return response

@app.before_request
def handle_options_preflight():
    if request.method == "OPTIONS":
        resp = make_response()
        return set_cors_headers(resp)

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": TOKEN
}

# --------------------------
# Utilities
# --------------------------
def consultar_ixc_registro(endpoint, payload, listar=True):
    url = f"{HOST}/{endpoint}"
    headers = {"Content-Type": "application/json", "Authorization": TOKEN}
    if listar:
        headers["ixcsoft"] = "listar"
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        data = resp.json()
    except Exception as e:
        return None, f"Erro IXC {endpoint}: {str(e)}"
    total = int(data.get("total") or 0)
    if total == 0:
        return None, f"Nenhum registro encontrado em {endpoint}."
    return data["registros"][0], None

def get_city_id_ixc(city_name):
    if not city_name:
        return None
    payload = {"qtype": "nome", "query": city_name, "oper": "=", "page": "1", "rp": "1"}
    registro, err = consultar_ixc_registro("cidade", payload, listar=True)
    if err:
        return None
    return registro.get("id") or registro.get("ID") or None

def format_date_br_with_time(date_iso, period):
    if not date_iso:
        return ""
    try:
        date_part = date_iso.split("T")[0]
        dt = datetime.strptime(date_part, "%Y-%m-%d")
        hour = {"comercial":"10:00:00","manha":"09:00:00","tarde":"14:00:00"}.get(period,"10:00:00")
        return dt.strftime("%d/%m/%Y") + " " + hour
    except Exception:
        return date_iso

def try_format_date(field, registro, fmt="%d/%m/%Y"):
    if field in registro and registro[field]:
        try:
            return pd.to_datetime(registro[field]).strftime(fmt)
        except Exception:
            return registro[field]
    return registro.get(field, "")

def geocode_address(address, city=None, state=None):
    """
    Fallback para obter lat/lng via Nominatim (OpenStreetMap).
    Ativar via .env GEOCODE_ENABLED=true.
    """
    if not address:
        return None, None
    q_parts = [address]
    if city:
        q_parts.append(city)
    if state:
        q_parts.append(state)
    q = ", ".join(q_parts)
    params = {"q": q, "format": "json", "limit": 1}
    url = "https://nominatim.openstreetmap.org/search?" + urlencode(params)
    headers = {"User-Agent": GEOCODE_USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        results = resp.json()
        if not results:
            return None, None
        lat = results[0].get("lat")
        lon = results[0].get("lon")
        return lat, lon
    except Exception as e:
        print("Geocode error:", e)
        return None, None

# --------------------------
# Rota CEP: tenta AwesomeAPI -> ViaCEP -> (opcional) Nominatim
# --------------------------
@app.route("/api/cep/<cep>", methods=["GET", "OPTIONS"])
def buscar_cep(cep):
    try:
        cep_digits = re.sub(r"\D", "", cep)
        if len(cep_digits) != 8:
            return jsonify({"error": "CEP inválido"}), 400

        # 1) Tenta AwesomeAPI (retorna lat/lng quando disponível)
        awesome_url = f"https://cep.awesomeapi.com.br/json/{cep_digits}"
        try:
            r = requests.get(awesome_url, timeout=6)
            if r.status_code == 200:
                dados = r.json()
                # Normaliza campos
                address = dados.get("address") or (dados.get("address_type", "") + " " + dados.get("address_name", "")) or ""
                district = dados.get("district") or dados.get("bairro") or ""
                city = dados.get("city") or ""
                state = dados.get("state") or ""
                lat = dados.get("lat") or dados.get("latitude") or ""
                lng = dados.get("lng") or dados.get("longitude") or ""
                city_ibge = dados.get("city_ibge") or dados.get("ibge") or ""
                # tenta obter cityId via IXC
                city_id = get_city_id_ixc(city)
                result = {
                    "cep": dados.get("cep") or cep_digits,
                    "address": address,
                    "district": district,
                    "city": city,
                    "state": state,
                    "lat": lat or "",
                    "lng": lng or "",
                    "city_ibge": city_ibge,
                    "cityId": city_id
                }
                # se lat/lng vieram já retornamos
                if result["lat"] and result["lng"]:
                    return jsonify(result)
                # caso awesomeapi tenha retornado, mas sem lat/lng, segue para fallback abaixo
        except Exception as e:
            print("AwesomeAPI error:", e)

        # 2) ViaCEP (padrão) - não tem lat/lng normalmente
        try:
            resp = requests.get(f"https://viacep.com.br/ws/{cep_digits}/json/", timeout=6)
            dados = resp.json()
            if dados.get("erro"):
                raise Exception("CEP não encontrado no ViaCEP")
            address = dados.get("logradouro") or ""
            district = dados.get("bairro") or ""
            city = dados.get("localidade") or ""
            state = dados.get("uf") or ""
            city_ibge = dados.get("ibge") or ""
        except Exception as e:
            # se falhar both, retorna erro
            print("ViaCEP error:", e)
            return jsonify({"error": "CEP não encontrado nos provedores"}), 404

        # tenta mapear cityId via IXC
        city_id = get_city_id_ixc(city)

        lat = ""
        lng = ""

        # 3) Se não tem lat/lng e geocode ativado, tenta Nominatim
        if GEOCODE_ENABLED:
            lat_g, lng_g = geocode_address(address, city, state)
            if lat_g and lng_g:
                lat, lng = lat_g, lng_g

        result = {
            "cep": cep_digits,
            "address": address,
            "district": district,
            "city": city,
            "state": state,
            "lat": lat or "",
            "lng": lng or "",
            "city_ibge": city_ibge,
            "cityId": city_id
        }
        return jsonify(result)

    except Exception as e:
        print("EXCEPTION buscar_cep:", e)
        return jsonify({"error": str(e)}), 500

# --------------------------
# Outros endpoints (cliente, cliente_contrato, get_login_id, transfer, update_contrato)
# Manter a lógica que você já tinha; abaixo coloquei implementações robustas e compatíveis
# --------------------------

@app.route("/api/cliente", methods=["POST", "OPTIONS"])
def rota_cliente_lookup():
    try:
        q = request.get_json(force=True) or {}
        query = (q.get("query") or "").strip()
        qtypes = [q.get("qtype") or "cnpj_cpf"]
        tried = []
        if not query:
            return jsonify({"error": "Parâmetro 'query' é obrigatório."}), 400

        url = f"{HOST}/cliente"
        headers = {"Authorization": TOKEN, "Content-Type": "application/json", "ixcsoft": "listar"}

        def format_cpf_cnpj(value):
            value = re.sub(r"\D", "", value)
            if len(value) == 11:
                return f"{value[:3]}.{value[3:6]}.{value[6:9]}-{value[9:]}"
            elif len(value) == 14:
                return f"{value[:2]}.{value[2:5]}.{value[5:8]}/{value[8:12]}-{value[12:]}"
            return value

        def call_ixc(qtype_inner, query_inner):
            if qtype_inner == "cnpj_cpf":
                query_inner = format_cpf_cnpj(query_inner)
            payload = {"qtype": qtype_inner, "query": query_inner, "oper": "=", "page": "1", "rp": "1"}
            try:
                resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
                return resp.json(), payload, None
            except Exception as e:
                return None, payload, str(e)

        data, payload_sent, err = call_ixc(qtypes[0], query)
        tried.append(payload_sent)
        if err:
            return jsonify({"error": err, "tried_payloads": tried}), 500

        total = int(data.get("total") or 0)
        if total == 0:
            query_digits = re.sub(r"\D", "", query)
            if query_digits != query:
                data, payload_sent, err = call_ixc(qtypes[0], query_digits)
                tried.append(payload_sent)
                if err:
                    return jsonify({"error": err, "tried_payloads": tried}), 500
                total = int(data.get("total") or 0)
        if total == 0:
            for alt_qtype in ["cpf", "cpf_cliente", "id"]:
                if alt_qtype not in qtypes:
                    data, payload_sent, err = call_ixc(alt_qtype, query)
                    tried.append(payload_sent)
                    if err:
                        continue
                    total = int(data.get("total") or 0)
                    if total > 0:
                        break
        if total == 0:
            return jsonify({"error": "Nenhum registro encontrado em cliente.", "tried_payloads": tried}), 400
        return jsonify(data["registros"][0])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/cliente_contrato", methods=["POST", "OPTIONS"])
def rota_contrato_lookup():
    try:
        payload = request.get_json() or {}
        qtype = payload.get("qtype")
        query = payload.get("query") or payload.get("contractId") or payload.get("id_contrato") or payload.get("clientId") or payload.get("id_cliente")
        if not qtype:
            if payload.get("clientId") or payload.get("id_cliente"):
                qtype = "id_cliente"
                query = payload.get("clientId") or payload.get("id_cliente")
            else:
                qtype = "id"
                query = payload.get("contractId") or payload.get("id_contrato") or payload.get("query")
        if not query:
            return jsonify({"error": "Parâmetro 'query' (contractId ou clientId) é obrigatório."}), 400

        page = payload.get("page", "1")
        rp = payload.get("rp", "50")
        q = {"qtype": qtype, "query": str(query), "oper": "=", "page": str(page), "rp": str(rp)}
        headers_listar = {**HEADERS, "ixcsoft": "listar"}
        res = requests.post(f"{HOST}/cliente_contrato", headers=headers_listar, data=json.dumps(q), timeout=30)
        try:
            data = res.json()
        except Exception:
            return jsonify({"error": f"Erro parse response IXC cliente_contrato: {res.status_code} - {res.text}"}), 400
        total = int(data.get("total") or 0)
        if total == 0:
            return jsonify({"error": "Nenhum contrato encontrado para esse cliente.", "data": data}), 400
        return jsonify(data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def get_login_id(contract_id):
    try:
        payload = {"qtype": "id_contrato", "query": str(contract_id), "oper": "=", "page": "1", "rp": "1"}
        headers_listar = {**HEADERS, "ixcsoft": "listar"}
        resp = requests.post(f"{HOST}/radusuarios", headers=headers_listar, data=json.dumps(payload), timeout=30)
        try:
            data = resp.json()
        except Exception as e:
            return None, f"Erro parse resposta radusuarios: {str(e)} - status {resp.status_code} - text: {resp.text}"

        if "registros" not in data or len(data["registros"]) == 0:
            return None, "Login não encontrado para o contrato"

        registro = data["registros"][0]
        # tenta diferentes chaves que podem conter o id-login
        for key in ("id_login", "id", "ID", "login"):
            val = registro.get(key)
            if val is not None and str(val).strip() != "":
                return str(val), None

        snippet = {k: registro.get(k) for k in ("id", "id_login", "login")}
        return None, f"Campo id_login não encontrado no registro. Registro (chaves principais): {json.dumps(snippet, ensure_ascii=False)}"
    except Exception as e:
        return None, str(e)

@app.route("/api/transfer", methods=["POST", "OPTIONS"])
def rota_transfer():
    try:
        data = request.get_json() or {}
        id_cliente = data.get("clientId") or data.get("id_cliente")
        id_contrato = data.get("contractId") or data.get("id_contrato")
        if not id_cliente or not id_contrato:
            return jsonify({"error": "ID do cliente e contrato são obrigatórios."}), 400

        id_tecnico = data.get("id_tecnico") or "147"
        nome_cliente = data.get("nome_cliente") or ""
        telefone = data.get("telefone") or ""
        valueType = data.get("valueType") or data.get("valor") or ""
        valor = data.get("taxValue") if valueType == "taxa" else ("Isento mediante a renovação da fidelidade" if valueType == "renovacao" else "")
        scheduledDate = data.get("scheduledDate")
        period = data.get("period") or data.get("periodo") or ""
        data_str = format_date_br_with_time(scheduledDate, period)

        endereco = data.get("address") or data.get("endereco") or ""
        numero = data.get("number") or data.get("numero") or ""
        bairro = data.get("neighborhood") or data.get("bairro") or ""
        cep = data.get("cep") or ""
        cidade = data.get("cidade") or data.get("city") or ""
        complemento = data.get("complemento") or data.get("complement") or ""

        endereco_antigo = data.get("oldAddress") or data.get("endereco_antigo") or ""
        numero_antigo = data.get("oldNumber") or data.get("old_numero") or ""
        bairro_antigo = data.get("oldNeighborhood") or data.get("old_bairro") or ""
        cep_antigo = data.get("oldCep") or ""
        cidade_antiga = data.get("oldCity") or ""
        des_porta = data.get("portaNumber") or data.get("des_porta") or ""

        # aceita diferentes nomes para lat/lng
        lat = data.get("lat") or data.get("latitude") or None
        lng = data.get("lng") or data.get("longitude") or None
        city_ibge = data.get("city_ibge") or data.get("cityIbge") or data.get("city_ibge_code") or None

        # fallback geocode se permitido
        if (not lat or not lng) and GEOCODE_ENABLED:
            try:
                lat_g, lng_g = geocode_address(endereco, cidade or None, data.get("state") or None)
                if lat_g and lng_g:
                    lat, lng = lat or lat_g, lng or lng_g
                    print(f"Geocode fallback found lat/lng: {lat}/{lng}")
            except Exception as e:
                print("Geocode fallback failed:", e)

        print("DEBUG: transfer incoming lat/lng:", lat, lng, "city_ibge:", city_ibge)

        id_login, err_login = get_login_id(id_contrato)
        if err_login:
            return jsonify({"error": err_login}), 400

        mensagem = f"""\n\n
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

        resp_ticket = requests.post(f"{HOST}/su_ticket", headers=HEADERS, data=json.dumps(payload_ticket), timeout=30)
        if resp_ticket.status_code != 200:
            return jsonify({"error": f"Erro ao criar ticket: {resp_ticket.status_code} - {resp_ticket.text}"}), 400
        ticket_data = resp_ticket.json()
        id_ticket = ticket_data.get("id")

        payload_busca_os = {"qtype": "id_ticket", "query": id_ticket, "oper": "=", "page": "1", "rp": "1"}
        headers_listar = {**HEADERS, "ixcsoft": "listar"}
        resp_os_busca = requests.post(f"{HOST}/su_oss_chamado", headers=headers_listar, data=json.dumps(payload_busca_os), timeout=30)
        os_data = resp_os_busca.json()
        if str(os_data.get("total", 0)) == "0":
            return jsonify({"error": "Nenhuma OS encontrada para o ticket criado."}), 400
        id_os = os_data["registros"][0]["id"]
        mensagem_atual = os_data["registros"][0].get("mensagem") or mensagem

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
        resp_put = requests.put(f"{HOST}/su_oss_chamado/{id_os}", headers=HEADERS, data=json.dumps(payload_agenda), timeout=30)
        if resp_put.status_code != 200:
            return jsonify({"error": f"Erro ao agendar OS: {resp_put.status_code} - {resp_put.text}"}), 400

        resp_proto = requests.post(f"{HOST}/gerar_protocolo_atendimento", headers={**HEADERS, "ixcsoft": "inserir"}, timeout=30)
        protocolo = resp_proto.text

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
        resp_des = requests.post(f"{HOST}/su_oss_chamado", headers=HEADERS, data=json.dumps(payload_des), timeout=30)
        if resp_des.status_code != 200:
            return jsonify({"error": f"Erro ao criar OS desativação: {resp_des.status_code} - {resp_des.text}"}), 400

        # atualizar contrato (GET + PUT) — adiciona latitude/longitude/city_ibge/complemento quando vierem
        payload_get = {"qtype": "id", "query": str(id_contrato), "oper": "=", "page": "1", "rp": "1"}
        res_contrato = requests.post(f"{HOST}/cliente_contrato", headers=headers_listar, data=json.dumps(payload_get), timeout=30)
        contrato_data = res_contrato.json()
        if "registros" not in contrato_data or len(contrato_data["registros"]) == 0:
            return jsonify({"error": "Contrato não encontrado"}), 400

        registro = contrato_data["registros"][0]
        registro["endereco"] = endereco
        registro["numero"] = numero
        registro["bairro"] = bairro
        registro["cep"] = cep
        registro["cidade"] = cidade
        registro["complemento"] = complemento

        if lat:
            registro["latitude"] = lat
        if lng:
            registro["longitude"] = lng
        if city_ibge:
            registro["city_ibge"] = city_ibge

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

        if "ultima_atualizacao" in registro:
            registro.pop("ultima_atualizacao", None)

        url_put = f"{HOST}/cliente_contrato/{id_contrato}"
        headers_put_endereco = {"Content-Type": "application/json", "Authorization": TOKEN}
        res_put_endereco = requests.put(url_put, headers=headers_put_endereco, data=json.dumps(registro), timeout=30)
        if res_put_endereco.status_code != 200:
            return jsonify({"error": f"Erro ao atualizar contrato: {res_put_endereco.status_code} - {res_put_endereco.text}"}), 400

        return jsonify({
            "message": "Transferência, desativação e atualização do endereço realizadas com sucesso!",
            "id_ticket": id_ticket,
            "id_os_transferencia": id_os,
            "id_os_desativacao": resp_des.json().get("id")
        }), 200

    except Exception as e:
        print("EXCEPTION:", str(e))
        return jsonify({"error": str(e)}), 500

@app.route("/api/update_contrato", methods=["POST", "OPTIONS"])
def rota_update_contrato():
    try:
        data = request.get_json() or {}
        id_contrato = data.get("contractId") or data.get("id_contrato")
        if not id_contrato:
            return jsonify({"error": "ID do contrato (contractId) é obrigatório."}), 400

        endereco = data.get("address") or data.get("endereco") or ""
        numero = data.get("number") or data.get("numero") or ""
        bairro = data.get("neighborhood") or data.get("bairro") or ""
        cep = data.get("cep") or ""
        cidade = data.get("cidade") or data.get("city") or ""
        estado = data.get("state") or ""
        latitude = data.get("lat") or data.get("latitude") or ""
        longitude = data.get("lng") or data.get("longitude") or ""
        city_ibge = data.get("city_ibge") or ""
        motivo_cancelamento = data.get("motivo_cancelamento", " ")
        complemento = data.get("complement") or data.get("complemento") or "" 

        payload_get = {"qtype": "id", "query": str(id_contrato), "oper": "=", "page": "1", "rp": "1"}
        headers_listar = {**HEADERS, "ixcsoft": "listar"}
        res = requests.post(f"{HOST}/cliente_contrato", headers=headers_listar, data=json.dumps(payload_get), timeout=30)
        contrato_data = res.json()
        if "registros" not in contrato_data or len(contrato_data["registros"]) == 0:
            return jsonify({"error": "Contrato não encontrado"}), 400

        registro = contrato_data["registros"][0]
        registro["endereco"] = endereco
        registro["numero"] = numero
        registro["bairro"] = bairro
        registro["cep"] = cep
        registro["cidade"] = cidade
        registro["complemento"] = complemento 
        registro["estado"] = estado
        if latitude:
            registro["latitude"] = latitude
        if longitude:
            registro["longitude"] = longitude
        if city_ibge:
            registro["city_ibge"] = city_ibge

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

        url_put = f"{HOST}/cliente_contrato/{id_contrato}"
        headers_put = {"Content-Type": "application/json", "Authorization": TOKEN}
        res_put = requests.put(url_put, headers=headers_put, data=json.dumps(registro), timeout=30)
        if res_put.status_code != 200:
            return jsonify({"error": f"Erro ao atualizar contrato: {res_put.status_code} - {res_put.text}"}), 400

        confirm_res = requests.post(f"{HOST}/cliente_contrato", headers={**HEADERS, "ixcsoft": "listar"}, data=json.dumps(payload_get), timeout=30)
        return jsonify({"message": "Contrato atualizado com sucesso", "put_response": res_put.json()}), 200

    except Exception as e:
        print("EXCEPTION update_contrato:", str(e))
        return jsonify({"error": str(e)}), 500

# --------------------------
# Execução
# --------------------------
if __name__ == "__main__":
    print("Running app with HOST_API:", HOST, "GEOCODE_ENABLED:", GEOCODE_ENABLED)
    app.run(host="0.0.0.0", port=5000, debug=True)
