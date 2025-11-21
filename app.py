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
        print(f"Erro ao buscar cidade: {err}")
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
    Atenção: respeitar política de uso do Nominatim (rate limits).
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

def parse_bool(value):
    """Normaliza valores booleanos vindos do frontend (True/False, 'true'/'false', 1/0)."""
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    v = str(value).strip().lower()
    if v in ("1", "true", "t", "yes", "y"):
        return True
    if v in ("0", "false", "f", "no", "n", ""):
        return False
    return None

@app.route("/api/cep/<cep>", methods=["GET"])
def buscar_cep(cep):
    try:
        # Tenta AwesomeAPI primeiro
        res_awesome = requests.get(f"https://cep.awesomeapi.com.br/json/{cep}", timeout=50)
        
        if res_awesome.status_code == 200:
            data = res_awesome.json()
            city_name = data.get("city")
            city_id = get_city_id_ixc(city_name)

            return jsonify({
                "cep": data.get("cep"),
                "address": data.get("address"),
                "district": data.get("district"),
                "city": city_name,
                "state": data.get("state"),
                "cityId": str(city_id) if city_id else None,
                "city_ibge": data.get("city_ibge"),
                "lat": data.get("lat"),
                "lng": data.get("lng"),
                "source": "awesomeapi"
            }), 200
        
        # Se AwesomeAPI falhar, tenta ViaCEP
        print("AwesomeAPI falhou, tentando ViaCEP...")
        res_viacep = requests.get(f"https://viacep.com.br/ws/{cep}/json/", timeout=450)
        
        if res_viacep.status_code == 200 and not res_viacep.json().get("erro"):
            data = res_viacep.json()
            city_name = data.get("localidade")
            city_id = get_city_id_ixc(city_name)

            return jsonify({
                "cep": data.get("cep"),
                "address": data.get("logradouro"),
                "district": data.get("bairro"),
                "city": city_name,
                "state": data.get("uf"),
                "cityId": str(city_id) if city_id else None,
                "city_ibge": data.get("ibge"),
                "lat": "",
                "lng": "",
                "source": "viacep"
            }), 200
        
        return jsonify({"error": "CEP não encontrado em nenhuma base"}), 404
        
    except requests.exceptions.Timeout:
        return jsonify({"error": "Timeout ao buscar CEP"}), 408
    except Exception as e:
        print("Erro ao buscar CEP:", str(e))
        return jsonify({"error": "Erro interno do servidor"}), 500

# --------------------------
# listar condomínios (proxy para IXC)
# --------------------------
@app.route("/api/condominios", methods=["GET"])
def listar_condominios():
    """
    Retorna lista de condominios do IXC (cliente_condominio).
    Aceita query params opcionais: page, rp, qtype, query
    """
    try:
        page = request.args.get("page", "1")
        rp = request.args.get("rp", "9999")
        qtype = request.args.get("qtype", "")
        query = request.args.get("query", "")

        payload = {
            "qtype": qtype,
            "query": query,
            "oper": "=",
            "page": str(page),
            "rp": str(rp)
        }
        headers_listar = {**HEADERS, "ixcsoft": "listar"}
        resp = requests.post(f"{HOST}/cliente_condominio", headers=headers_listar, data=json.dumps(payload), timeout=30)
        try:
            data = resp.json()
        except Exception:
            return jsonify({"error": "Resposta inválida do IXC", "raw": resp.text}), 500

        registros = data.get("registros") or []
        # Mapeia os campos úteis (inclui cep e id_cidade agora)
        simplified = []
        for r in registros:
            simplified.append({
                "id": r.get("id"),
                "condominio": r.get("condominio"),
                "endereco": r.get("endereco"),
                "numero": r.get("numero"),
                "bairro": r.get("bairro"),
                "cep": r.get("cep"),
                "id_cidade": r.get("id_cidade"),
                "bloco_unico": r.get("bloco_unico")
            })
        return jsonify({"total": data.get("total", 0), "registros": simplified}), 200
    except Exception as e:
        print("EXCEPTION /api/condominios:", str(e))
        return jsonify({"error": str(e)}), 500

# --------------------------
# Rotas de lookup cliente e contrato
# --------------------------
@app.route("/api/cliente", methods=["POST", "OPTIONS"])
def rota_cliente_lookup():
    # -> mesma implementação do seu app (ou a que você já tem)
    try:
        q = request.get_json(force=True) or {}
        query = (q.get("query") or "").strip()
        qtypes = [q.get("qtype") or "cnpj_cpf"]
        tried = []
        if not query:
            return jsonify({"error": "Parâmetro 'query' é obrigatório."}), 400

        url = f"{HOST}/cliente"
        headers = {
            "Authorization": TOKEN,
            "Content-Type": "application/json",
            "ixcsoft": "listar"
        }

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
            payload = {
                "qtype": qtype_inner,
                "query": query_inner,
                "oper": "=",
                "page": "1",
                "rp": "1"
            }
            try:
                resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
                data = resp.json()
                return data, payload, None
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
            return jsonify({
                "error": "Nenhum registro encontrado em cliente.",
                "tried_payloads": tried
            }), 400
        return jsonify(data["registros"][0])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/cliente_contrato", methods=["POST", "OPTIONS"])
def rota_contrato_lookup():
    try:
        payload = request.get_json() or {}
        qtype = payload.get("qtype")
        query = (
            payload.get("query")
            or payload.get("contractId")
            or payload.get("id_contrato")
            or payload.get("clientId")
            or payload.get("id_cliente")
        )

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
        q = {
            "qtype": qtype,
            "query": str(query),
            "oper": "=",
            "page": str(page),
            "rp": str(rp)
        }

        headers_listar = {**HEADERS, "ixcsoft": "listar"}
        res = requests.post(f"{HOST}/cliente_contrato", headers=headers_listar, data=json.dumps(q), timeout=30)

        try:
            data = res.json()
        except Exception:
            return jsonify({"error": f"Erro ao interpretar resposta do IXC: {res.status_code} - {res.text}"}), 400

        registros_orig = data.get("registros") or []

        # -----------------------
        # Funções utilitárias
        # -----------------------
        def extract_status_code(r):
            try:
                s = (
                    r.get("status")
                    or r.get("situacao")
                    or r.get("st")
                    or r.get("status_contrato")
                    or r.get("statusContrato")
                    or r.get("status_internet")
                    or ""
                )
                s = str(s).strip().upper()
                return s[:1] if s else ""
            except Exception:
                return ""

        def is_endereco_padrao_s(r):
            try:
                v = r.get("endereco_padrao_cliente") or r.get("endereco_padrao") or r.get("enderecoPadrao") or ""
                s = str(v).strip().upper()
                return s in ("S", "1", "TRUE", "T", "SIM", "Y")
            except Exception:
                return False

        def has_any_address_info(r):
            for k in ("endereco_novo", "novo_endereco", "endereco", "address", "logradouro"):
                if r.get(k):
                    return True
            for k in ("cep_novo", "cep", "CEP", "Cep"):
                if r.get(k):
                    return True
            return False

        # -----------------------
        # Fallback: preenche endereço do cliente se necessário
        # -----------------------
        enriched_registros = []
        for r in registros_orig:
            registro = dict(r)

            try:
                if is_endereco_padrao_s(registro) and not has_any_address_info(registro):
                    id_cliente = registro.get("id_cliente") or registro.get("id")
                    if id_cliente:
                        payload_cliente = {
                            "qtype": "id",
                            "query": str(id_cliente),
                            "oper": "=",
                            "page": "1",
                            "rp": "1"
                        }
                        resp_cli = requests.post(
                            f"{HOST}/cliente",
                            headers=headers_listar,
                            data=json.dumps(payload_cliente),
                            timeout=30
                        )
                        try:
                            data_cli = resp_cli.json()
                        except Exception:
                            data_cli = None

                        if data_cli and data_cli.get("registros"):
                            cli = data_cli["registros"][0]
                            endereco_cli = cli.get("endereco") or cli.get("address") or cli.get("logradouro") or ""
                            numero_cli = cli.get("numero") or cli.get("number") or cli.get("nro") or ""
                            bairro_cli = cli.get("bairro") or cli.get("neighborhood") or ""
                            cep_cli = cli.get("cep") or cli.get("CEP") or ""
                            complemento_cli = cli.get("complemento") or cli.get("complement") or ""

                            if endereco_cli:
                                registro["endereco_novo"] = registro.get("endereco_novo") or endereco_cli
                            if numero_cli:
                                registro["numero_novo"] = registro.get("numero_novo") or numero_cli
                            if bairro_cli:
                                registro["bairro_novo"] = registro.get("bairro_novo") or bairro_cli
                            if cep_cli:
                                registro["cep_novo"] = registro.get("cep_novo") or cep_cli
                            if complemento_cli:
                                registro["complemento_novo"] = registro.get("complemento_novo") or complemento_cli
            except Exception:
                pass

            enriched_registros.append(registro)

        # -----------------------
        # Filtra contratos válidos (exclui Desistido/Inativo)
        # -----------------------
        registros_filtrados = [
            r for r in enriched_registros if extract_status_code(r) not in ("D", "I")
        ]

        response_payload = {
            "total": len(registros_filtrados),
            "registros": registros_filtrados
        }

        return jsonify(response_payload), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# get_login_id
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
        for key in ("id_login", "id", "ID", "login"):
            val = registro.get(key)
            if val is not None and str(val).strip() != "":
                return str(val), None

        snippet = {k: registro.get(k) for k in ("id", "id_login", "login")}
        return None, f"Campo id_login não encontrado no registro. Registro (chaves principais): {json.dumps(snippet, ensure_ascii=False)}"
    except Exception as e:
        return None, str(e)

# --------------------------
# Rota principal: transfer
# --------------------------
@app.route("/api/transfer", methods=["POST", "OPTIONS"])
def rota_transfer():
    try:
        data = request.get_json() or {}

        id_cliente = data.get("clientId") or data.get("id_cliente")
        id_contrato = data.get("contractId") or data.get("id_contrato")
        if not id_cliente or not id_contrato:
            return jsonify({"error": "ID do cliente e contrato são obrigatórios."}), 400

        # Campos básicos
        id_tecnico = data.get("id_tecnico") or "147"
        nome_cliente = data.get("nome_cliente") or ""
        telefone = data.get("telefone") or ""

        # --- valor (taxa, renovação ou isento)
        valueType = (data.get("valueType") or data.get("valor") or "").lower()
        valor = ""
        if valueType == "taxa":
            valor = data.get("taxValue") or ""
        elif valueType == "renovacao":
            valor = "Isento mediante a renovação da fidelidade"

        scheduledDate = data.get("scheduledDate")
        period = data.get("period") or data.get("periodo") or ""
        data_str = format_date_br_with_time(scheduledDate, period)

        # --- melhor horário/reserva (aceita várias chaves do frontend)
        melhor_horario_reserva = (
            data.get("melhor_horario_reserva")
            or data.get("melhor_horario_agenda")
            or data.get("melhor_horario")
            or data.get("periodo_letra")  # alias se algum frontend enviar diferente
            or ""
        )

        # Normaliza para as letras esperadas pelo IXC: M / T / N / Q
        _map_mh = {
            "manha": "M", "manhã": "M", "m": "M",
            "tarde": "T", "t": "T",
            "noite": "N", "n": "N",
            "comercial": "Q", "comercialmente": "Q",
            "q": "Q",
            "": "Q"
        }

        mh_key = str(melhor_horario_reserva).strip().lower()
        # se vier já como 'M'/'T' etc, aceita diretamente (case-insensitive)
        if mh_key.upper() in ("M", "T", "N", "Q"):
            melhor_horario_agenda_val = mh_key.upper()
        else:
            melhor_horario_agenda_val = _map_mh.get(mh_key, _map_mh.get(mh_key.replace("ã", "a"), "Q"))


        endereco = data.get("address") or data.get("endereco") or ""
        numero = data.get("number") or data.get("numero") or ""
        bairro = data.get("neighborhood") or data.get("bairro") or ""
        cep = data.get("cep") or ""
        cidade = data.get("cidade") or data.get("city") or ""
        complemento = data.get("complemento") or data.get("complement") or ""

        # Campos antigos
        endereco_antigo = data.get("oldAddress") or data.get("endereco_antigo") or ""
        numero_antigo = data.get("oldNumber") or data.get("old_numero") or ""
        bairro_antigo = data.get("oldNeighborhood") or data.get("old_bairro") or ""
        cep_antigo = data.get("oldCep") or ""
        cidade_antiga = data.get("oldCity") or ""

        des_porta = data.get("portaNumber") or data.get("des_porta") or ""

        # Condomínio (aceita várias chaves do frontend)
        condominio_id = data.get("id_condominio") or data.get("condominio") or data.get("condominioId") or data.get("condominio_id")
        bloco = data.get("bloco") or data.get("block") or data.get("apto_bloco") or ""
        apartamento = data.get("apartamento") or data.get("apartment") or data.get("apt") or ""

        # Normaliza isCondominio
        is_condominio = parse_bool(data.get("isCondominio") if "isCondominio" in data else data.get("is_condominio"))

        # Coordenadas / cidade IBGE
        lat = data.get("lat") or data.get("latitude") or None
        lng = data.get("lng") or data.get("longitude") or None
        city_ibge = data.get("city_ibge") or data.get("cityIbge") or data.get("city_ibge_code") or None

        # Se não tiver lat/lng e geocode estiver ativo
        if (not lat or not lng) and GEOCODE_ENABLED:
            try:
                lat_g, lng_g = geocode_address(endereco, cidade or None, data.get("state") or None)
                if lat_g and lng_g:
                    lat, lng = lat or lat_g, lng or lng_g
                    print(f"Geocode fallback found lat/lng: {lat}/{lng}")
            except Exception as e:
                print("Geocode fallback failed:", e)

        print("DEBUG: transfer incoming lat/lng:", lat, lng, "city_ibge:", city_ibge)

        # 1) obter id_login
        id_login, err_login = get_login_id(id_contrato)
        if err_login:
            return jsonify({"error": err_login}), 400

        # --- formatar data e período
        date_display = ""
        if scheduledDate:
            try:
                date_part = str(scheduledDate).split("T")[0].split(" ")[0]
                dt = datetime.strptime(date_part, "%Y-%m-%d")
                date_display = dt.strftime("%d/%m/%Y")
            except Exception:
                date_display = str(scheduledDate)

        period_map = {"comercial": "Comercial", "manha": "Manhã", "tarde": "Tarde"}
        period_display = period_map.get((period or "").lower(), (period or "").capitalize())

        # formatar CEP
        cep_display = cep or ""
        try:
            cep_digits = re.sub(r"\D", "", str(cep_display or ""))
            if len(cep_digits) == 8:
                cep_display = f"{cep_digits[:5]}-{cep_digits[5:]}"
        except Exception:
            pass

        # --- campos de porta ---
        has_porta = data.get("hasPorta")
        porta_num = data.get("portaNumber") or data.get("des_porta") or ""

        # se veio como string "true"/"false", normaliza pra boolean
        if isinstance(has_porta, str):
            has_porta = has_porta.lower() in ["true", "1", "yes", "sim"]

        # monta o texto final da porta
        if has_porta:
            des_porta = f"Porta {porta_num}" if porta_num else "Porta não informada"
        else:
            des_porta = "Não foi possível localizar porta"

        # 2) criar ticket
        mensagem = f"""
Quem receberá: {nome_cliente}
Contato: {telefone}
Títular/Responsável Legal: {nome_cliente}
Valor: {valor}
Data/Período: {date_display} - {period_display}
*Qualquer valor referente ao serviço deverá ser pago no momento da visita técnica, cliente ciente.

Cliente solicita transferência de endereço.
Endereço atual/Desativação de porta: {endereco_antigo}, {numero_antigo} - {bairro_antigo} / {des_porta}
Novo endereço: {endereco}, {numero} - {bairro}, {cep_display}
""".strip()

        id_tecnico_TICKET = str(data.get("id_responsavel_tecnico") or "147")  # puxando o ID do Login

        resp_proto = requests.post(f"{HOST}/gerar_protocolo_atendimento", headers={**HEADERS, "ixcsoft": "inserir"}, timeout=30)
        protocoloAtendimento = resp_proto.text

        payload_ticket = {
            "tipo": "C",
            "protocolo": protocoloAtendimento,
            "id_cliente": id_cliente,
            "id_login": id_login,
            "id_contrato": id_contrato,
            "menssagem": mensagem,
            "id_responsavel_tecnico": id_tecnico_TICKET,
            "melhor_horario_reserva": melhor_horario_agenda_val,
            "id_resposta": "88",
            "id_ticket_origem": "I",
            "id_assunto": "80",
            "origem_endereco": "CC",
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

        # 3) buscar OS para pegar o PROTOCOLO
        payload_busca_os = {"qtype": "id_ticket", "query": id_ticket, "oper": "=", "page": "1", "rp": "1"}
        resp_os_busca = requests.post(f"{HOST}/su_oss_chamado", headers={**HEADERS, "ixcsoft": "listar"}, data=json.dumps(payload_busca_os), timeout=30)
        os_data = resp_os_busca.json()
        if str(os_data.get("total", 0)) == "0":
            return jsonify({"error": "Nenhuma OS encontrada para o ticket criado."}), 400
        
        # AQUI ESTÁ A MUDANÇA PRINCIPAL - PEGANDO O PROTOCOLO DA OS
        id_os = os_data["registros"][0]["id"]
        protocolo_os = os_data["registros"][0].get("protocolo", "")  # ← NOVO CAMPO ADICIONADO
        mensagem_atual = os_data["registros"][0].get("mensagem") or mensagem

        print(f"DEBUG: Protocolo da OS encontrado: {protocolo_os}")

        # 4) agendar OS (ATUALIZADO: primeiro chama alterar_setor para garantir status/setor, depois faz PUT detalhado)
        payload_agenda = {
            "tipo": "C",
            "id": id_os,
            "id_ticket": id_ticket,
            "id_cliente": id_cliente,
            "id_login": id_login,
            "id_contrato_kit": id_contrato,
            "id_tecnico": id_tecnico,
            "melhor_horario_agenda": melhor_horario_agenda_val,
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

        # Aplica dados de condomínio se presentes
        if is_condominio:
            if condominio_id:
                payload_agenda["id_condominio"] = str(condominio_id)
            if bloco:
                payload_agenda["bloco"] = str(bloco)
            if apartamento:
                payload_agenda["apartamento"] = str(apartamento)
        else:
            payload_agenda["id_condominio"] = ""
            payload_agenda["bloco"] = ""
            payload_agenda["apartamento"] = ""

        # ---- novo: chamar su_oss_chamado_alterar_setor para garantir status/setor ----
        alterar_url = f"{HOST}/su_oss_chamado_alterar_setor"
        # data no formato "YYYY-MM-DD HH:MM:SS"
        data_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        alterar_payload = {
            "id_chamado": str(id_os),
            "id_setor": str(payload_agenda.get("setor", 1)),
            "id_tecnico": str(payload_agenda.get("id_tecnico") or id_tecnico or ""),
            "id_assunto": str(payload_agenda.get("id_assunto", "")),
            "mensagem": f"Agendado automaticamente pelo sistemas (Automação Marques).\n Atendente responsavel pelo agendamento: {id_tecnico_TICKET}",
            "status": "AG",
            "data": data_now,
            "id_evento": "",
            "latitude": payload_agenda.get("latitude", "") or "",
            "longitude": payload_agenda.get("longitude", "") or "",
            "gps_time": "",
            "id_ticket": str(id_ticket),
            "id_filial": str(payload_agenda.get("id_filial", 2))
        }
        headers_alterar = {**HEADERS, "Content-Type": "application/json"}

        success = False
        # tenta PUT primeiro (conforme atualização do dev)
        try:
            resp_alter_put = requests.put(alterar_url, headers=headers_alterar, data=json.dumps(alterar_payload), timeout=30)
            if resp_alter_put.status_code >= 200 and resp_alter_put.status_code < 300:
                success = True
            else:
                print(f"PUT su_oss_chamado_alterar_setor retornou status {resp_alter_put.status_code}: {resp_alter_put.text}")
        except Exception as e:
            print("Erro no PUT su_oss_chamado_alterar_setor:", e)

        if not success:
            # fallback para POST (observado como funcional nos logs)
            try:
                resp_alter_post = requests.post(alterar_url, headers=headers_alterar, data=json.dumps(alterar_payload), timeout=30)
                if resp_alter_post.status_code >= 200 and resp_alter_post.status_code < 300:
                    success = True
                else:
                    print(f"POST su_oss_chamado_alterar_setor retornou status {resp_alter_post.status_code}: {resp_alter_post.text}")
            except Exception as e:
                print("Erro no POST su_oss_chamado_alterar_setor:", e)

        if not success:
            return jsonify({"error": "Erro ao aplicar alterar_setor (status/setor). Veja logs do servidor para detalhes."}), 400

        # ---- após garantir setor/status, mantém o PUT detalhado original para gravar endereço/datas/etc. ----
        resp_put = requests.put(f"{HOST}/su_oss_chamado/{id_os}", headers=HEADERS, data=json.dumps(payload_agenda), timeout=30)
        if resp_put.status_code != 200:
            return jsonify({"error": f"Erro ao agendar OS (PUT detalhado): {resp_put.status_code} - {resp_put.text}"}), 400

        # 5) OS desativação
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

        # 6) Atualiza contrato no IXC
        payload_get = {"qtype": "id", "query": str(id_contrato), "oper": "=", "page": "1", "rp": "1"}
        res_contrato = requests.post(f"{HOST}/cliente_contrato", headers={**HEADERS, "ixcsoft": "listar"}, data=json.dumps(payload_get), timeout=30)
        contrato_data = res_contrato.json()
        if "registros" not in contrato_data or len(contrato_data["registros"]) == 0:
            return jsonify({"error": "Contrato não encontrado"}), 400

        registro = contrato_data["registros"][0]

        registro.update({
            "endereco": endereco,
            "numero": numero,
            "bairro": bairro,
            "cep": cep,
            "cidade": cidade,
            "complemento": complemento,
        })

        # Lógica para condomínio
        if is_condominio is False:
            registro["id_condominio"] = ""
            registro["bloco"] = ""
            registro["apartamento"] = ""
        else:
            if condominio_id:
                registro["id_condominio"] = str(condominio_id)
            if bloco is not None:
                registro["bloco"] = str(bloco)
            if apartamento is not None:
                registro["apartamento"] = str(apartamento)

        if lat:
            registro["latitude"] = lat
        if lng:
            registro["longitude"] = lng
        if city_ibge:
            registro["city_ibge"] = city_ibge

        registro["endereco_padrao_cliente"] = "N"
        registro["motivo_cancelamento"] = registro.get("motivo_cancelamento", " ")

        if "ultima_atualizacao" in registro:
            registro.pop("ultima_atualizacao", None)

        res_put_endereco = requests.put(f"{HOST}/cliente_contrato/{id_contrato}", headers={"Content-Type": "application/json", "Authorization": TOKEN}, data=json.dumps(registro), timeout=30)
        if res_put_endereco.status_code != 200:
            return jsonify({"error": f"Erro ao atualizar contrato: {res_put_endereco.status_code} - {res_put_endereco.text}"}), 400

        # AQUI ESTÁ A MUDANÇA NA RESPOSTA - RETORNANDO O PROTOCOLO DA OS
        return jsonify({
            "message": "Transferência, desativação e atualização do endereço realizadas com sucesso!",
            "id_ticket": id_ticket,
            "id_os_transferencia": id_os,
            "id_os_desativacao": resp_des.json().get("id"),
            "protocolo_os": protocolo_os  # ← NOVO CAMPO ADICIONADO NA RESPOSTA
        }), 200

    except Exception as e:
        print("EXCEPTION:", str(e))
        return jsonify({"error": str(e)}), 500

# --------------------------
# Endpoint dedicado para atualizar contrato
# --------------------------
@app.route("/api/update_contrato", methods=["POST", "OPTIONS"])
def rota_update_contrato():
    try:
        data = request.get_json() or {}
        id_contrato = data.get("contractId") or data.get("id_contrato")
        if not id_contrato:
            return jsonify({"error": "ID do contrato (contractId / id_contrato) é obrigatório."}), 400

        # Campos opcionais do frontend
        endereco = data.get("address") or data.get("endereco")
        numero = data.get("number") or data.get("numero")
        bairro = data.get("neighborhood") or data.get("bairro")
        cep_input = data.get("cep")
        cidade = data.get("cidade") or data.get("city")
        estado = data.get("state") or data.get("estado")
        lat = data.get("lat") or data.get("latitude")
        lng = data.get("lng") or data.get("longitude")
        city_ibge = data.get("city_ibge") or data.get("cityIbge")
        complemento = data.get("complement") or data.get("complemento")

        # condominio fields
        condominio_id = data.get("id_condominio") or data.get("condominio") or data.get("condominioId") or None
        bloco = data.get("bloco") or data.get("block") or data.get("apartmentBlock") or None
        apartamento = data.get("apartamento") or data.get("apartment") or data.get("apt") or None

        # lê isCondominio (normaliza)
        is_condominio = parse_bool(data.get("isCondominio") if "isCondominio" in data else data.get("is_condominio"))

        # 1) Buscar contrato atual
        payload_get = {"qtype": "id", "query": str(id_contrato), "oper": "=", "page": "1", "rp": "1"}
        headers_listar = {"Content-Type": "application/json", "Authorization": TOKEN, "ixcsoft": "listar"}
        resp_get = requests.post(f"{HOST}/cliente_contrato", headers=headers_listar, data=json.dumps(payload_get), timeout=30)
        dados = resp_get.json()

        if "registros" not in dados or not dados["registros"]:
            return jsonify({"error": "Contrato não encontrado no IXC."}), 404

        registro = dados["registros"][0]

        # extrai id do cliente para possível sincronização com tabela cliente
        id_cliente = registro.get("id_cliente") or registro.get("id") and None  # fallback se campo diferente
        # se não encontrou id_cliente diretamente, tenta outras chaves comuns
        if not id_cliente:
            for k in ("id_cliente", "id_cliente_contrato", "id_cliente_fk", "cliente_id"):
                if registro.get(k):
                    id_cliente = registro.get(k)
                    break

        # 2) Atualizar apenas campos recebidos (no contrato)
        if endereco is not None:
            registro["endereco"] = endereco
        if numero is not None:
            registro["numero"] = numero
        if bairro is not None:
            registro["bairro"] = bairro
        if cidade is not None:
            registro["cidade"] = str(cidade)
        if estado is not None:
            registro["estado"] = estado
        if complemento is not None:
            registro["complemento"] = complemento
        if lat is not None:
            registro["latitude"] = lat
        if lng is not None:
            registro["longitude"] = lng
        if city_ibge is not None:
            registro["city_ibge"] = city_ibge

        # limpar campos se não for condomínio (quando explicitamente false)
        if is_condominio is False:
            registro["id_condominio"] = ""
            registro["bloco"] = ""
            registro["apartamento"] = ""
        else:
            # só atualiza se vier algo do frontend
            if condominio_id is not None:
                registro["id_condominio"] = str(condominio_id)
            if bloco is not None:
                registro["bloco"] = str(bloco)
            if apartamento is not None:
                registro["apartamento"] = str(apartamento)

        # ---------- Antes de enviar o PUT do contrato, descobrir quantos contratos o cliente tem ----------
        contrato_count = None
        try:
            if id_cliente:
                q_count = {"qtype": "id_cliente", "query": str(id_cliente), "oper": "=", "page": "1", "rp": "1"}
                resp_count = requests.post(f"{HOST}/cliente_contrato", headers=headers_listar, data=json.dumps(q_count), timeout=30)
                data_count = resp_count.json()
                contrato_count = int(data_count.get("total") or 0)
                print(f"DEBUG: cliente {id_cliente} possui {contrato_count} contratos (total reportado).")
        except Exception as e:
            print("WARN: falha ao obter quantidade de contratos do cliente:", e)
            contrato_count = None

        # 3) CEP: enviar apenas se válido (8 dígitos) e formatado com "-"
        def clean_digits(s): return re.sub(r"\D", "", str(s or ""))
        def all_zeros(s): return s != "" and set(s) == {"0"}

        if cep_input:
            cep_digits = clean_digits(cep_input)
            if cep_digits and len(cep_digits) == 8 and not all_zeros(cep_digits):
                registro["cep"] = f"{cep_digits[:5]}-{cep_digits[5:]}"  # garante XXXXX-XXX
        else:
            cep_atual = clean_digits(registro.get("cep", ""))
            if cep_atual and len(cep_atual) == 8 and not all_zeros(cep_atual):
                registro["cep"] = f"{cep_atual[:5]}-{cep_atual[5:]}"
            else:
                registro.pop("cep", None)

        # 4) Campos obrigatórios como string
        for key in ["id_filial", "id_cliente", "id_tipo_contrato", "id_vd_contrato", "id_modelo"]:
            registro[key] = str(registro.get(key, "") or "1")

        # 5) Motivo cancelamento fixo
        registro["motivo_cancelamento"] = " "

        # 6) Formatar datas
        def fmt_date(field, fmt="%d/%m/%Y"):
            try:
                if registro.get(field):
                    return pd.to_datetime(registro[field]).strftime(fmt)
            except Exception:
                pass
            return registro.get(field, "")

        registro["data"] = fmt_date("data")
        registro["data_expiracao"] = fmt_date("data_expiracao")
        registro["data_ativacao"] = fmt_date("data_ativacao")
        registro["data_renovacao"] = fmt_date("data_renovacao")
        registro["data_cadastro_sistema"] = fmt_date("data_cadastro_sistema", "%d/%m/%Y %H:%M:%S")

        # 7) Ajustes finais
        registro["endereco_padrao_cliente"] = "N"
        registro["ultima_atualizacao"] = "CURRENT_TIMESTAMP"

        # 8) Remover campos problemáticos
        for f in ("interacao_pendente", "imp_obs", "imp_importacao", "document_photo", "selfie_photo"):
            registro.pop(f, None)

        # 9) Log para debug
        print("=== PUT /cliente_contrato payload ===")
        print(json.dumps(registro, ensure_ascii=False, indent=2))
        print("====================================")

        # 10) Enviar PUT para atualizar o contrato
        url_put = f"{HOST}/cliente_contrato/{id_contrato}"
        headers_put = {"Content-Type": "application/json", "Authorization": TOKEN}
        resp_put = requests.put(url_put, headers=headers_put, data=json.dumps(registro), timeout=30)

        try:
            resp_json = resp_put.json()
        except Exception:
            resp_json = {"type": "error", "message": "Resposta IXC não-JSON", "raw": resp_put.text}

        if resp_put.status_code != 200 or resp_json.get("type") == "error":
            return jsonify({
                "erro": "Falha ao atualizar contrato no IXC",
                "status_code": resp_put.status_code,
                "resposta": resp_json
            }), 400

        # --------------------------------------------------------------------
        # 11) Se o cliente tem apenas 1 contrato ativo, atualiza também a tabela /cliente
        # --------------------------------------------------------------------
        try:
            contrato_count = None
            if id_cliente:
                try:
                    # pede muitos registros para podermos filtrar localmente por status
                    q_count = {"qtype": "id_cliente", "query": str(id_cliente), "oper": "=", "page": "1", "rp": "9999"}
                    resp_count = requests.post(f"{HOST}/cliente_contrato", headers=headers_listar, data=json.dumps(q_count), timeout=30)
                    data_count = resp_count.json()
                    registros = data_count.get("registros") or []

                    def is_active_contract_local(r):
                        try:
                            s = (r.get("status") or r.get("situacao") or r.get("st") or "")
                            return str(s).strip().upper() == "A"
                        except Exception:
                            return False

                    ativos = [r for r in registros if is_active_contract_local(r)]
                    contrato_count = len(ativos)
                    print(f"DEBUG: cliente {id_cliente} possui {len(registros)} contratos (raw) e {contrato_count} contratos ativos.")
                except Exception as e:
                    print("WARN: falha ao obter quantidade de contratos do cliente:", e)
                    contrato_count = None

            # só sincroniza cliente se houver exatamente 1 contrato ativo
            if contrato_count == 1 and id_cliente:
                # buscar cliente atual
                payload_cliente_get = {"qtype": "id", "query": str(id_cliente), "oper": "=", "page": "1", "rp": "1"}
                resp_cliente_get = requests.post(f"{HOST}/cliente", headers=headers_listar, data=json.dumps(payload_cliente_get), timeout=30)
                cliente_data = resp_cliente_get.json()
                if "registros" in cliente_data and cliente_data["registros"]:
                    registro_cliente = cliente_data["registros"][0]

                    # atualiza somente os campos recebidos (mesma lógica do contrato)
                    if endereco is not None:
                        registro_cliente["endereco"] = endereco
                    if numero is not None:
                        registro_cliente["numero"] = numero
                    if bairro is not None:
                        registro_cliente["bairro"] = bairro
                    if cidade is not None:
                        registro_cliente["cidade"] = str(cidade)
                    if estado is not None:
                        registro_cliente["estado"] = estado
                    if complemento is not None:
                        registro_cliente["complemento"] = complemento
                    if lat is not None:
                        registro_cliente["latitude"] = lat
                    if lng is not None:
                        registro_cliente["longitude"] = lng
                    if city_ibge is not None:
                        registro_cliente["city_ibge"] = city_ibge

                    # condomínio no cliente
                    if is_condominio is False:
                        registro_cliente["id_condominio"] = ""
                        registro_cliente["bloco"] = ""
                        registro_cliente["apartamento"] = ""
                    else:
                        if condominio_id is not None:
                            registro_cliente["id_condominio"] = str(condominio_id)
                        if bloco is not None:
                            registro_cliente["bloco"] = str(bloco)
                        if apartamento is not None:
                            registro_cliente["apartamento"] = str(apartamento)

                    # CEP cliente: mesma formatação/validação
                    if cep_input:
                        cep_digits = clean_digits(cep_input)
                        if cep_digits and len(cep_digits) == 8 and not all_zeros(cep_digits):
                            registro_cliente["cep"] = f"{cep_digits[:5]}-{cep_digits[5:]}"
                    else:
                        cep_atual_cliente = clean_digits(registro_cliente.get("cep", ""))
                        if cep_atual_cliente and len(cep_atual_cliente) == 8 and not all_zeros(cep_atual_cliente):
                            registro_cliente["cep"] = f"{cep_atual_cliente[:5]}-{cep_atual_cliente[5:]}"
                        else:
                            registro_cliente.pop("cep", None)

                    # limpa campos problemáticos no cliente (mesma lista)
                    for f in ("interacao_pendente", "imp_obs", "imp_importacao", "document_photo", "selfie_photo"):
                        registro_cliente.pop(f, None)

                    # log e PUT no cliente
                    print("=== PUT /cliente payload (sync from single-active-contract client) ===")
                    print(json.dumps(registro_cliente, ensure_ascii=False, indent=2))
                    print("=====================================================================")

                    url_put_cliente = f"{HOST}/cliente/{id_cliente}"
                    resp_put_cliente = requests.put(url_put_cliente, headers=headers_put, data=json.dumps(registro_cliente), timeout=30)

                    try:
                        resp_put_cliente_json = resp_put_cliente.json()
                    except Exception:
                        resp_put_cliente_json = {"type": "error", "message": "Resposta IXC não-JSON", "raw": resp_put_cliente.text}

                    if resp_put_cliente.status_code != 200 or resp_put_cliente_json.get("type") == "error":
                        # não falha todo o fluxo por conta da sync do cliente, apenas loga e retorna aviso parcial
                        print("WARN: Falha ao atualizar cliente (mesmo após atualizar contrato):", resp_put_cliente.status_code, resp_put_cliente.text)
                else:
                    print("DEBUG: Não foi possível obter registro do cliente para sincronização (vazio).")
        except Exception as e:
            print("WARN: Erro durante sincronização de /cliente:", e)

        # 12) tudo ok
        return jsonify({"mensagem": "Contrato atualizado com sucesso (e cliente sincronizado quando aplicável).", "resposta": resp_json}), 200

    except Exception as e:
        print("EXCEPTION /update_contrato:", str(e))
        return jsonify({"error": str(e)}), 500

# --------------------------
# Endpoint dedicado para mudança de ponto
# --------------------------
@app.route("/api/mudanca", methods=["POST", "OPTIONS"])
def rota_mudanca():
    try:
        data = request.get_json() or {}

        id_cliente = data.get("clientId") or data.get("id_cliente")
        id_contrato = data.get("contractId") or data.get("id_contrato")
        if not id_cliente or not id_contrato:
            return jsonify({"error": "ID do cliente e contrato são obrigatórios."}), 400

        # Campos básicos
        id_tecnico = data.get("id_tecnico") or "147"
        nome_cliente = data.get("nome_cliente") or ""
        telefone = data.get("telefone") or ""

        # --- valor (taxa, renovação ou isento)
        valueType = (data.get("valueType") or data.get("valor") or "").lower()
        valor = ""
        if valueType == "taxa":
            valor = data.get("taxValue") or ""
        elif valueType == "renovacao":
            valor = "Isento mediante a renovação da fidelidade"

        scheduledDate = data.get("scheduledDate")
        period = data.get("period") or data.get("periodo") or ""
        data_str = format_date_br_with_time(scheduledDate, period)

        # --- melhor horário/reserva
        melhor_horario_reserva = (
            data.get("melhor_horario_reserva")
            or data.get("melhor_horario_agenda")
            or data.get("melhor_horario")
            or data.get("periodo_letra")
            or ""
        )

        # Normaliza para as letras esperadas pelo IXC: M / T / N / Q
        _map_mh = {
            "manha": "M", "manhã": "M", "m": "M",
            "tarde": "T", "t": "T",
            "noite": "N", "n": "N",
            "comercial": "Q", "comercialmente": "Q",
            "q": "Q",
            "": "Q"
        }

        mh_key = str(melhor_horario_reserva).strip().lower()
        if mh_key.upper() in ("M", "T", "N", "Q"):
            melhor_horario_agenda_val = mh_key.upper()
        else:
            melhor_horario_agenda_val = _map_mh.get(mh_key, _map_mh.get(mh_key.replace("ã", "a"), "Q"))

        # Dados específicos da mudança de ponto
        observacoes = data.get("observacoes") or data.get("observacao") or ""

        # 1) obter id_login
        id_login, err_login = get_login_id(id_contrato)
        if err_login:
            return jsonify({"error": err_login}), 400

        # --- formatar data e período
        date_display = ""
        if scheduledDate:
            try:
                date_part = str(scheduledDate).split("T")[0].split(" ")[0]
                dt = datetime.strptime(date_part, "%Y-%m-%d")
                date_display = dt.strftime("%d/%m/%Y")
            except Exception:
                date_display = str(scheduledDate)

        period_map = {"comercial": "Comercial", "manha": "Manhã", "tarde": "Tarde"}
        period_display = period_map.get((period or "").lower(), (period or "").capitalize())

        # 2) criar ticket com a mensagem específica EXATA
        mensagem = f"""MUDANÇA DE PONTO - PRIORIZAR PERÍODO INDICADO

Nome do contato: {nome_cliente}
Tel: {telefone}
Data/Período: {date_display} - {period_display}
Valor: {valor}
Motivo da Mudança: {observacoes}""".strip()

        id_tecnico_TICKET = str(data.get("id_responsavel_tecnico") or "147")

        resp_proto = requests.post(f"{HOST}/gerar_protocolo_atendimento", headers={**HEADERS, "ixcsoft": "inserir"}, timeout=30)
        protocoloAtendimento = resp_proto.text

        payload_ticket = {
            "tipo": "C",
            "protocolo": protocoloAtendimento,
            "id_cliente": id_cliente,
            "id_login": id_login,
            "id_contrato": id_contrato,
            "menssagem": mensagem,
            "id_responsavel_tecnico": id_tecnico_TICKET,
            "melhor_horario_reserva": melhor_horario_agenda_val,
            "id_resposta": "225",
            "id_ticket_origem": "I",
            "id_assunto": "259",
            "origem_endereco": "CC",
            "titulo": "Mudança de Ponto",
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

        # 3) buscar OS para pegar o PROTOCOLO
        payload_busca_os = {"qtype": "id_ticket", "query": id_ticket, "oper": "=", "page": "1", "rp": "1"}
        resp_os_busca = requests.post(f"{HOST}/su_oss_chamado", headers={**HEADERS, "ixcsoft": "listar"}, data=json.dumps(payload_busca_os), timeout=30)
        os_data = resp_os_busca.json()
        if str(os_data.get("total", 0)) == "0":
            return jsonify({"error": "Nenhuma OS encontrada para o ticket criado."}), 400
        
        id_os = os_data["registros"][0]["id"]
        protocolo_os = os_data["registros"][0].get("protocolo", "")
        mensagem_atual = os_data["registros"][0].get("mensagem") or mensagem

        print(f"DEBUG: Protocolo da OS encontrado: {protocolo_os}")

        # 4) agendar OS com ID do assunto 259
        payload_agenda = {
            "tipo": "C",
            "id": id_os,
            "id_ticket": id_ticket,
            "id_cliente": id_cliente,
            "id_login": id_login,
            "id_contrato_kit": id_contrato,
            "id_tecnico": id_tecnico,
            "melhor_horario_agenda": melhor_horario_agenda_val,
            "status": "AG",
            "id_filial": 2,
            "id_assunto": 259,
            "setor": 1,
            "prioridade": "N",
            "origem_endereco": "CC",
            "mensagem_resposta": "Agendado via API - Mudança de Ponto",
            "data_agenda": data_str,
            "data_agenda_final": data_str,
            "mensagem": mensagem_atual
        }

        # ---- chamar su_oss_chamado_alterar_setor para garantir status/setor ----
        alterar_url = f"{HOST}/su_oss_chamado_alterar_setor"
        data_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        alterar_payload = {
            "id_chamado": str(id_os),
            "id_setor": str(payload_agenda.get("setor", 1)),
            "id_tecnico": str(payload_agenda.get("id_tecnico") or id_tecnico or ""),
            "id_assunto": str(payload_agenda.get("id_assunto", "")),
            "mensagem": f"Agendado automaticamente pelo sistemas (Automação Marques).\n Atendente responsavel pelo agendamento: {id_tecnico_TICKET}",
            "status": "AG",
            "data": data_now,
            "id_evento": "",
            "latitude": "",
            "longitude": "",
            "gps_time": "",
            "id_ticket": str(id_ticket),
            "id_filial": str(payload_agenda.get("id_filial", 2))
        }
        headers_alterar = {**HEADERS, "Content-Type": "application/json"}

        success = False
        try:
            resp_alter_put = requests.put(alterar_url, headers=headers_alterar, data=json.dumps(alterar_payload), timeout=30)
            if resp_alter_put.status_code >= 200 and resp_alter_put.status_code < 300:
                success = True
            else:
                print(f"PUT su_oss_chamado_alterar_setor retornou status {resp_alter_put.status_code}: {resp_alter_put.text}")
        except Exception as e:
            print("Erro no PUT su_oss_chamado_alterar_setor:", e)

        if not success:
            try:
                resp_alter_post = requests.post(alterar_url, headers=headers_alterar, data=json.dumps(alterar_payload), timeout=30)
                if resp_alter_post.status_code >= 200 and resp_alter_post.status_code < 300:
                    success = True
                else:
                    print(f"POST su_oss_chamado_alterar_setor retornou status {resp_alter_post.status_code}: {resp_alter_post.text}")
            except Exception as e:
                print("Erro no POST su_oss_chamado_alterar_setor:", e)

        if not success:
            return jsonify({"error": "Erro ao aplicar alterar_setor (status/setor). Veja logs do servidor para detalhes."}), 400

        # ---- PUT detalhado para gravar dados completos ----
        resp_put = requests.put(f"{HOST}/su_oss_chamado/{id_os}", headers=HEADERS, data=json.dumps(payload_agenda), timeout=30)
        if resp_put.status_code != 200:
            return jsonify({"error": f"Erro ao agendar OS (PUT detalhado): {resp_put.status_code} - {resp_put.text}"}), 400

        return jsonify({
            "message": "Mudança de ponto agendada com sucesso!",
            "id_ticket": id_ticket,
            "id_os_mudanca": id_os,
            "protocolo_os": protocolo_os
        }), 200

    except Exception as e:
        print("EXCEPTION /api/mudanca:", str(e))
        return jsonify({"error": str(e)}), 500

# --------------------------
# Endpoint dedicado para sem conexão
# --------------------------
@app.route("/api/semconexao", methods=["POST", "OPTIONS"])
def rota_semconexao():
    try:
        data = request.get_json() or {}

        id_cliente = data.get("clientId") or data.get("id_cliente")
        id_contrato = data.get("contractId") or data.get("id_contrato")
        if not id_cliente or not id_contrato:
            return jsonify({"error": "ID do cliente e contrato são obrigatórios."}), 400

        # Campos básicos
        id_tecnico = data.get("id_tecnico") or "147"
        nome_cliente = data.get("nome_cliente") or ""
        telefone = data.get("telefone") or ""

        # --- valor (taxa, renovação ou isento)
        valueType = (data.get("valueType") or data.get("valor") or "").lower()
        valor = ""
        if valueType == "taxa":
            valor = data.get("taxValue") or ""
        elif valueType == "renovacao":
            valor = "Isento mediante a renovação da fidelidade"

        scheduledDate = data.get("scheduledDate")
        period = data.get("period") or data.get("periodo") or ""
        data_str = format_date_br_with_time(scheduledDate, period)

        # --- melhor horário/reserva
        melhor_horario_reserva = (
            data.get("melhor_horario_reserva")
            or data.get("melhor_horario_agenda")
            or data.get("melhor_horario")
            or data.get("periodo_letra")
            or ""
        )

        # Normaliza para as letras esperadas pelo IXC: M / T / N / Q
        _map_mh = {
            "manha": "M", "manhã": "M", "m": "M",
            "tarde": "T", "t": "T",
            "noite": "N", "n": "N",
            "comercial": "Q", "comercialmente": "Q",
            "q": "Q",
            "": "Q"
        }

        mh_key = str(melhor_horario_reserva).strip().lower()
        if mh_key.upper() in ("M", "T", "N", "Q"):
            melhor_horario_agenda_val = mh_key.upper()
        else:
            melhor_horario_agenda_val = _map_mh.get(mh_key, _map_mh.get(mh_key.replace("ã", "a"), "Q"))

        # Dados específicos da mudança de ponto
        observacoes = data.get("observacoes") or data.get("observacao") or ""

        # 1) obter id_login
        id_login, err_login = get_login_id(id_contrato)
        if err_login:
            return jsonify({"error": err_login}), 400

        # --- formatar data e período
        date_display = ""
        if scheduledDate:
            try:
                date_part = str(scheduledDate).split("T")[0].split(" ")[0]
                dt = datetime.strptime(date_part, "%Y-%m-%d")
                date_display = dt.strftime("%d/%m/%Y")
            except Exception:
                date_display = str(scheduledDate)

        period_map = {"comercial": "Comercial", "manha": "Manhã", "tarde": "Tarde"}
        period_display = period_map.get((period or "").lower(), (period or "").capitalize())

        # 2) criar ticket com a mensagem específica EXATA
        mensagem = f"""SEM CONEXÃO - PRIORIZAR PERÍODO INDICADO

Nome do contato: {nome_cliente}
Tel: {telefone}
Data/Período: {date_display} - {period_display}
Motivo do Agendamento: {observacoes}""".strip()

        id_tecnico_TICKET = str(data.get("id_responsavel_tecnico") or "147")

        resp_proto = requests.post(f"{HOST}/gerar_protocolo_atendimento", headers={**HEADERS, "ixcsoft": "inserir"}, timeout=30)
        protocoloAtendimento = resp_proto.text

        payload_ticket = {
            "tipo": "C",
            "protocolo": protocoloAtendimento,
            "id_cliente": id_cliente,
            "id_login": id_login,
            "id_contrato": id_contrato,
            "menssagem": mensagem,
            "id_responsavel_tecnico": id_tecnico_TICKET,
            "melhor_horario_reserva": melhor_horario_agenda_val,
            "id_resposta": "221",
            "id_ticket_origem": "I",
            "id_assunto": "166",
            "origem_endereco": "CC",
            "titulo": "Sem Conexão",
            "su_status": "AG",
            "id_ticket_setor": "3",
            "prioridade": "M",
            "id_wfl_processo": "8",
            "setor": "3",
            "id_wfl_processo": "125"
        }

        resp_ticket = requests.post(f"{HOST}/su_ticket", headers=HEADERS, data=json.dumps(payload_ticket), timeout=30)
        if resp_ticket.status_code != 200:
            return jsonify({"error": f"Erro ao criar ticket: {resp_ticket.status_code} - {resp_ticket.text}"}), 400
        ticket_data = resp_ticket.json()
        id_ticket = ticket_data.get("id")

        # 3) buscar OS para pegar o PROTOCOLO
        payload_busca_os = {"qtype": "id_ticket", "query": id_ticket, "oper": "=", "page": "1", "rp": "1"}
        resp_os_busca = requests.post(f"{HOST}/su_oss_chamado", headers={**HEADERS, "ixcsoft": "listar"}, data=json.dumps(payload_busca_os), timeout=30)
        os_data = resp_os_busca.json()
        if str(os_data.get("total", 0)) == "0":
            return jsonify({"error": "Nenhuma OS encontrada para o ticket criado."}), 400
        
        id_os = os_data["registros"][0]["id"]
        protocolo_os = os_data["registros"][0].get("protocolo", "")
        mensagem_atual = os_data["registros"][0].get("mensagem") or mensagem

        print(f"DEBUG: Protocolo da OS encontrado: {protocolo_os}")

        # 4) agendar OS com ID do assunto 259
        payload_agenda = {
            "tipo": "C",
            "id": id_os,
            "id_ticket": id_ticket,
            "id_cliente": id_cliente,
            "id_login": id_login,
            "id_contrato_kit": id_contrato,
            "id_tecnico": id_tecnico,
            "melhor_horario_agenda": melhor_horario_agenda_val,
            "status": "AG",
            "id_filial": 2,
            "id_assunto": 166,
            "setor": 1,
            "prioridade": "N",
            "origem_endereco": "CC",
            "mensagem_resposta": "Agendado via API - Sem Conexão",
            "data_agenda": data_str,
            "data_agenda_final": data_str,
            "mensagem": mensagem_atual
        }

        # ---- chamar su_oss_chamado_alterar_setor para garantir status/setor ----
        alterar_url = f"{HOST}/su_oss_chamado_alterar_setor"
        data_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        alterar_payload = {
            "id_chamado": str(id_os),
            "id_setor": str(payload_agenda.get("setor", 1)),
            "id_tecnico": str(payload_agenda.get("id_tecnico") or id_tecnico or ""),
            "id_assunto": str(payload_agenda.get("id_assunto", "")),
            "mensagem": f"Agendado automaticamente pelo sistemas (Automação Marques).\n Atendente responsavel pelo agendamento: {id_tecnico_TICKET}",
            "status": "AG",
            "data": data_now,
            "id_evento": "",
            "latitude": "",
            "longitude": "",
            "gps_time": "",
            "id_ticket": str(id_ticket),
            "id_filial": str(payload_agenda.get("id_filial", 2))
        }
        headers_alterar = {**HEADERS, "Content-Type": "application/json"}

        success = False
        try:
            resp_alter_put = requests.put(alterar_url, headers=headers_alterar, data=json.dumps(alterar_payload), timeout=30)
            if resp_alter_put.status_code >= 200 and resp_alter_put.status_code < 300:
                success = True
            else:
                print(f"PUT su_oss_chamado_alterar_setor retornou status {resp_alter_put.status_code}: {resp_alter_put.text}")
        except Exception as e:
            print("Erro no PUT su_oss_chamado_alterar_setor:", e)

        if not success:
            try:
                resp_alter_post = requests.post(alterar_url, headers=headers_alterar, data=json.dumps(alterar_payload), timeout=30)
                if resp_alter_post.status_code >= 200 and resp_alter_post.status_code < 300:
                    success = True
                else:
                    print(f"POST su_oss_chamado_alterar_setor retornou status {resp_alter_post.status_code}: {resp_alter_post.text}")
            except Exception as e:
                print("Erro no POST su_oss_chamado_alterar_setor:", e)

        if not success:
            return jsonify({"error": "Erro ao aplicar alterar_setor (status/setor). Veja logs do servidor para detalhes."}), 400

        # ---- PUT detalhado para gravar dados completos ----
        resp_put = requests.put(f"{HOST}/su_oss_chamado/{id_os}", headers=HEADERS, data=json.dumps(payload_agenda), timeout=30)
        if resp_put.status_code != 200:
            return jsonify({"error": f"Erro ao agendar OS (PUT detalhado): {resp_put.status_code} - {resp_put.text}"}), 400

        return jsonify({
            "message": "Sem conexão agendada com sucesso!",
            "id_ticket": id_ticket,
            "id_os_mudanca": id_os,
            "protocolo_os": protocolo_os
        }), 200

    except Exception as e:
        print("EXCEPTION /api/semconexao:", str(e))
        return jsonify({"error": str(e)}), 500

# --------------------------
# Endpoint dedicado para lentidão
# --------------------------
@app.route("/api/lentidao", methods=["POST", "OPTIONS"])
def rota_lentidao():
    try:
        data = request.get_json() or {}

        id_cliente = data.get("clientId") or data.get("id_cliente")
        id_contrato = data.get("contractId") or data.get("id_contrato")
        if not id_cliente or not id_contrato:
            return jsonify({"error": "ID do cliente e contrato são obrigatórios."}), 400

        # Campos básicos
        id_tecnico = data.get("id_tecnico") or "147"
        nome_cliente = data.get("nome_cliente") or ""
        telefone = data.get("telefone") or ""

        # --- valor (taxa, renovação ou isento)
        valueType = (data.get("valueType") or data.get("valor") or "").lower()
        valor = ""
        if valueType == "taxa":
            valor = data.get("taxValue") or ""
        elif valueType == "renovacao":
            valor = "Isento mediante a renovação da fidelidade"

        scheduledDate = data.get("scheduledDate")
        period = data.get("period") or data.get("periodo") or ""
        data_str = format_date_br_with_time(scheduledDate, period)

        # --- melhor horário/reserva
        melhor_horario_reserva = (
            data.get("melhor_horario_reserva")
            or data.get("melhor_horario_agenda")
            or data.get("melhor_horario")
            or data.get("periodo_letra")
            or ""
        )

        # Normaliza para as letras esperadas pelo IXC: M / T / N / Q
        _map_mh = {
            "manha": "M", "manhã": "M", "m": "M",
            "tarde": "T", "t": "T",
            "noite": "N", "n": "N",
            "comercial": "Q", "comercialmente": "Q",
            "q": "Q",
            "": "Q"
        }

        mh_key = str(melhor_horario_reserva).strip().lower()
        if mh_key.upper() in ("M", "T", "N", "Q"):
            melhor_horario_agenda_val = mh_key.upper()
        else:
            melhor_horario_agenda_val = _map_mh.get(mh_key, _map_mh.get(mh_key.replace("ã", "a"), "Q"))

        # Dados específicos da mudança de ponto
        observacoes = data.get("observacoes") or data.get("observacao") or ""

        # 1) obter id_login
        id_login, err_login = get_login_id(id_contrato)
        if err_login:
            return jsonify({"error": err_login}), 400

        # --- formatar data e período
        date_display = ""
        if scheduledDate:
            try:
                date_part = str(scheduledDate).split("T")[0].split(" ")[0]
                dt = datetime.strptime(date_part, "%Y-%m-%d")
                date_display = dt.strftime("%d/%m/%Y")
            except Exception:
                date_display = str(scheduledDate)

        period_map = {"comercial": "Comercial", "manha": "Manhã", "tarde": "Tarde"}
        period_display = period_map.get((period or "").lower(), (period or "").capitalize())

        # 2) criar ticket com a mensagem específica EXATA
        mensagem = f"""LENTIDÃO - PRIORIZAR PERÍODO INDICADO

Nome do contato: {nome_cliente}
Tel: {telefone}
Data/Período: {date_display} - {period_display}
Motivo do Agendamento: {observacoes}""".strip()

        id_tecnico_TICKET = str(data.get("id_responsavel_tecnico") or "147")

        resp_proto = requests.post(f"{HOST}/gerar_protocolo_atendimento", headers={**HEADERS, "ixcsoft": "inserir"}, timeout=30)
        protocoloAtendimento = resp_proto.text

        payload_ticket = {
            "tipo": "C",
            "protocolo": protocoloAtendimento,
            "id_cliente": id_cliente,
            "id_login": id_login,
            "id_contrato": id_contrato,
            "menssagem": mensagem,
            "id_responsavel_tecnico": id_tecnico_TICKET,
            "melhor_horario_reserva": melhor_horario_agenda_val,
            "id_resposta": "220",
            "id_ticket_origem": "I",
            "id_assunto": "167",
            "origem_endereco": "CC",
            "titulo": "Lentidão",
            "su_status": "AG",
            "id_ticket_setor": "3",
            "prioridade": "M",
            "id_wfl_processo": "8",
            "setor": "3",
            "id_wfl_processo": "124"
        }

        resp_ticket = requests.post(f"{HOST}/su_ticket", headers=HEADERS, data=json.dumps(payload_ticket), timeout=30)
        if resp_ticket.status_code != 200:
            return jsonify({"error": f"Erro ao criar ticket: {resp_ticket.status_code} - {resp_ticket.text}"}), 400
        ticket_data = resp_ticket.json()
        id_ticket = ticket_data.get("id")

        # 3) buscar OS para pegar o PROTOCOLO
        payload_busca_os = {"qtype": "id_ticket", "query": id_ticket, "oper": "=", "page": "1", "rp": "1"}
        resp_os_busca = requests.post(f"{HOST}/su_oss_chamado", headers={**HEADERS, "ixcsoft": "listar"}, data=json.dumps(payload_busca_os), timeout=30)
        os_data = resp_os_busca.json()
        if str(os_data.get("total", 0)) == "0":
            return jsonify({"error": "Nenhuma OS encontrada para o ticket criado."}), 400
        
        id_os = os_data["registros"][0]["id"]
        protocolo_os = os_data["registros"][0].get("protocolo", "")
        mensagem_atual = os_data["registros"][0].get("mensagem") or mensagem

        print(f"DEBUG: Protocolo da OS encontrado: {protocolo_os}")

        # 4) agendar OS com ID do assunto 259
        payload_agenda = {
            "tipo": "C",
            "id": id_os,
            "id_ticket": id_ticket,
            "id_cliente": id_cliente,
            "id_login": id_login,
            "id_contrato_kit": id_contrato,
            "id_tecnico": id_tecnico,
            "melhor_horario_agenda": melhor_horario_agenda_val,
            "status": "AG",
            "id_filial": 2,
            "id_assunto": 167,
            "setor": 1,
            "prioridade": "N",
            "origem_endereco": "CC",
            "mensagem_resposta": "Agendado via API - Lentidão",
            "data_agenda": data_str,
            "data_agenda_final": data_str,
            "mensagem": mensagem_atual
        }

        # ---- chamar su_oss_chamado_alterar_setor para garantir status/setor ----
        alterar_url = f"{HOST}/su_oss_chamado_alterar_setor"
        data_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        alterar_payload = {
            "id_chamado": str(id_os),
            "id_setor": str(payload_agenda.get("setor", 1)),
            "id_tecnico": str(payload_agenda.get("id_tecnico") or id_tecnico or ""),
            "id_assunto": str(payload_agenda.get("id_assunto", "")),
            "mensagem": f"Agendado automaticamente pelo sistemas (Automação Marques).\n Atendente responsavel pelo agendamento: {id_tecnico_TICKET}",
            "status": "AG",
            "data": data_now,
            "id_evento": "",
            "latitude": "",
            "longitude": "",
            "gps_time": "",
            "id_ticket": str(id_ticket),
            "id_filial": str(payload_agenda.get("id_filial", 2))
        }
        headers_alterar = {**HEADERS, "Content-Type": "application/json"}

        success = False
        try:
            resp_alter_put = requests.put(alterar_url, headers=headers_alterar, data=json.dumps(alterar_payload), timeout=30)
            if resp_alter_put.status_code >= 200 and resp_alter_put.status_code < 300:
                success = True
            else:
                print(f"PUT su_oss_chamado_alterar_setor retornou status {resp_alter_put.status_code}: {resp_alter_put.text}")
        except Exception as e:
            print("Erro no PUT su_oss_chamado_alterar_setor:", e)

        if not success:
            try:
                resp_alter_post = requests.post(alterar_url, headers=headers_alterar, data=json.dumps(alterar_payload), timeout=30)
                if resp_alter_post.status_code >= 200 and resp_alter_post.status_code < 300:
                    success = True
                else:
                    print(f"POST su_oss_chamado_alterar_setor retornou status {resp_alter_post.status_code}: {resp_alter_post.text}")
            except Exception as e:
                print("Erro no POST su_oss_chamado_alterar_setor:", e)

        if not success:
            return jsonify({"error": "Erro ao aplicar alterar_setor (status/setor). Veja logs do servidor para detalhes."}), 400

        # ---- PUT detalhado para gravar dados completos ----
        resp_put = requests.put(f"{HOST}/su_oss_chamado/{id_os}", headers=HEADERS, data=json.dumps(payload_agenda), timeout=30)
        if resp_put.status_code != 200:
            return jsonify({"error": f"Erro ao agendar OS (PUT detalhado): {resp_put.status_code} - {resp_put.text}"}), 400

        return jsonify({
            "message": "Lentidão agendada com sucesso!",
            "id_ticket": id_ticket,
            "id_os_mudanca": id_os,
            "protocolo_os": protocolo_os
        }), 200

    except Exception as e:
        print("EXCEPTION /api/lentidao:", str(e))
        return jsonify({"error": str(e)}), 500

# --------------------------
# Endpoint dedicado para quedas de conexão
# --------------------------
@app.route("/api/quedas", methods=["POST", "OPTIONS"])
def rota_quedas():
    try:
        data = request.get_json() or {}

        id_cliente = data.get("clientId") or data.get("id_cliente")
        id_contrato = data.get("contractId") or data.get("id_contrato")
        if not id_cliente or not id_contrato:
            return jsonify({"error": "ID do cliente e contrato são obrigatórios."}), 400

        # Campos básicos
        id_tecnico = data.get("id_tecnico") or "147"
        nome_cliente = data.get("nome_cliente") or ""
        telefone = data.get("telefone") or ""

        # --- valor (taxa, renovação ou isento)
        valueType = (data.get("valueType") or data.get("valor") or "").lower()
        valor = ""
        if valueType == "taxa":
            valor = data.get("taxValue") or ""
        elif valueType == "renovacao":
            valor = "Isento mediante a renovação da fidelidade"

        scheduledDate = data.get("scheduledDate")
        period = data.get("period") or data.get("periodo") or ""
        data_str = format_date_br_with_time(scheduledDate, period)

        # --- melhor horário/reserva
        melhor_horario_reserva = (
            data.get("melhor_horario_reserva")
            or data.get("melhor_horario_agenda")
            or data.get("melhor_horario")
            or data.get("periodo_letra")
            or ""
        )

        # Normaliza para as letras esperadas pelo IXC: M / T / N / Q
        _map_mh = {
            "manha": "M", "manhã": "M", "m": "M",
            "tarde": "T", "t": "T",
            "noite": "N", "n": "N",
            "comercial": "Q", "comercialmente": "Q",
            "q": "Q",
            "": "Q"
        }

        mh_key = str(melhor_horario_reserva).strip().lower()
        if mh_key.upper() in ("M", "T", "N", "Q"):
            melhor_horario_agenda_val = mh_key.upper()
        else:
            melhor_horario_agenda_val = _map_mh.get(mh_key, _map_mh.get(mh_key.replace("ã", "a"), "Q"))

        # Dados específicos da mudança de ponto
        observacoes = data.get("observacoes") or data.get("observacao") or ""

        # 1) obter id_login
        id_login, err_login = get_login_id(id_contrato)
        if err_login:
            return jsonify({"error": err_login}), 400

        # --- formatar data e período
        date_display = ""
        if scheduledDate:
            try:
                date_part = str(scheduledDate).split("T")[0].split(" ")[0]
                dt = datetime.strptime(date_part, "%Y-%m-%d")
                date_display = dt.strftime("%d/%m/%Y")
            except Exception:
                date_display = str(scheduledDate)

        period_map = {"comercial": "Comercial", "manha": "Manhã", "tarde": "Tarde"}
        period_display = period_map.get((period or "").lower(), (period or "").capitalize())

        # 2) criar ticket com a mensagem específica EXATA
        mensagem = f"""QUEDAS - PRIORIZAR PERÍODO INDICADO

Nome do contato: {nome_cliente}
Tel: {telefone}
Data/Período: {date_display} - {period_display}
Motivo do Agendamento: {observacoes}""".strip()

        id_tecnico_TICKET = str(data.get("id_responsavel_tecnico") or "147")

        resp_proto = requests.post(f"{HOST}/gerar_protocolo_atendimento", headers={**HEADERS, "ixcsoft": "inserir"}, timeout=30)
        protocoloAtendimento = resp_proto.text

        payload_ticket = {
            "tipo": "C",
            "protocolo": protocoloAtendimento,
            "id_cliente": id_cliente,
            "id_login": id_login,
            "id_contrato": id_contrato,
            "menssagem": mensagem,
            "id_responsavel_tecnico": id_tecnico_TICKET,
            "melhor_horario_reserva": melhor_horario_agenda_val,
            "id_resposta": "229",
            "id_ticket_origem": "I",
            "id_assunto": "169",
            "origem_endereco": "CC",
            "titulo": "Quedas de Conexão",
            "su_status": "AG",
            "id_ticket_setor": "3",
            "prioridade": "M",
            "id_wfl_processo": "8",
            "setor": "3",
            "id_wfl_processo": "130"
        }

        resp_ticket = requests.post(f"{HOST}/su_ticket", headers=HEADERS, data=json.dumps(payload_ticket), timeout=30)
        if resp_ticket.status_code != 200:
            return jsonify({"error": f"Erro ao criar ticket: {resp_ticket.status_code} - {resp_ticket.text}"}), 400
        ticket_data = resp_ticket.json()
        id_ticket = ticket_data.get("id")

        # 3) buscar OS para pegar o PROTOCOLO
        payload_busca_os = {"qtype": "id_ticket", "query": id_ticket, "oper": "=", "page": "1", "rp": "1"}
        resp_os_busca = requests.post(f"{HOST}/su_oss_chamado", headers={**HEADERS, "ixcsoft": "listar"}, data=json.dumps(payload_busca_os), timeout=30)
        os_data = resp_os_busca.json()
        if str(os_data.get("total", 0)) == "0":
            return jsonify({"error": "Nenhuma OS encontrada para o ticket criado."}), 400
        
        id_os = os_data["registros"][0]["id"]
        protocolo_os = os_data["registros"][0].get("protocolo", "")
        mensagem_atual = os_data["registros"][0].get("mensagem") or mensagem

        print(f"DEBUG: Protocolo da OS encontrado: {protocolo_os}")

        # 4) agendar OS com ID do assunto 259
        payload_agenda = {
            "tipo": "C",
            "id": id_os,
            "id_ticket": id_ticket,
            "id_cliente": id_cliente,
            "id_login": id_login,
            "id_contrato_kit": id_contrato,
            "id_tecnico": id_tecnico,
            "melhor_horario_agenda": melhor_horario_agenda_val,
            "status": "AG",
            "id_filial": 2,
            "id_assunto": 169,
            "setor": 1,
            "prioridade": "N",
            "origem_endereco": "CC",
            "mensagem_resposta": "Agendado via API - Quedas de Conexão",
            "data_agenda": data_str,
            "data_agenda_final": data_str,
            "mensagem": mensagem_atual
        }

        # ---- chamar su_oss_chamado_alterar_setor para garantir status/setor ----
        alterar_url = f"{HOST}/su_oss_chamado_alterar_setor"
        data_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        alterar_payload = {
            "id_chamado": str(id_os),
            "id_setor": str(payload_agenda.get("setor", 1)),
            "id_tecnico": str(payload_agenda.get("id_tecnico") or id_tecnico or ""),
            "id_assunto": str(payload_agenda.get("id_assunto", "")),
            "mensagem": f"Agendado automaticamente pelo sistemas (Automação Marques).\n Atendente responsavel pelo agendamento: {id_tecnico_TICKET}",
            "status": "AG",
            "data": data_now,
            "id_evento": "",
            "latitude": "",
            "longitude": "",
            "gps_time": "",
            "id_ticket": str(id_ticket),
            "id_filial": str(payload_agenda.get("id_filial", 2))
        }
        headers_alterar = {**HEADERS, "Content-Type": "application/json"}

        success = False
        try:
            resp_alter_put = requests.put(alterar_url, headers=headers_alterar, data=json.dumps(alterar_payload), timeout=30)
            if resp_alter_put.status_code >= 200 and resp_alter_put.status_code < 300:
                success = True
            else:
                print(f"PUT su_oss_chamado_alterar_setor retornou status {resp_alter_put.status_code}: {resp_alter_put.text}")
        except Exception as e:
            print("Erro no PUT su_oss_chamado_alterar_setor:", e)

        if not success:
            try:
                resp_alter_post = requests.post(alterar_url, headers=headers_alterar, data=json.dumps(alterar_payload), timeout=30)
                if resp_alter_post.status_code >= 200 and resp_alter_post.status_code < 300:
                    success = True
                else:
                    print(f"POST su_oss_chamado_alterar_setor retornou status {resp_alter_post.status_code}: {resp_alter_post.text}")
            except Exception as e:
                print("Erro no POST su_oss_chamado_alterar_setor:", e)

        if not success:
            return jsonify({"error": "Erro ao aplicar alterar_setor (status/setor). Veja logs do servidor para detalhes."}), 400

        # ---- PUT detalhado para gravar dados completos ----
        resp_put = requests.put(f"{HOST}/su_oss_chamado/{id_os}", headers=HEADERS, data=json.dumps(payload_agenda), timeout=30)
        if resp_put.status_code != 200:
            return jsonify({"error": f"Erro ao agendar OS (PUT detalhado): {resp_put.status_code} - {resp_put.text}"}), 400

        return jsonify({
            "message": "Quedas de Conexão agendada com sucesso!",
            "id_ticket": id_ticket,
            "id_os_mudanca": id_os,
            "protocolo_os": protocolo_os
        }), 200

    except Exception as e:
        print("EXCEPTION /api/quedas:", str(e))
        return jsonify({"error": str(e)}), 500

# --------------------------
# Endpoint dedicado para configurações de roteador
# --------------------------
@app.route("/api/config", methods=["POST", "OPTIONS"])
def rota_config():
    try:
        data = request.get_json() or {}

        id_cliente = data.get("clientId") or data.get("id_cliente")
        id_contrato = data.get("contractId") or data.get("id_contrato")
        if not id_cliente or not id_contrato:
            return jsonify({"error": "ID do cliente e contrato são obrigatórios."}), 400

        # Campos básicos
        id_tecnico = data.get("id_tecnico") or "147"
        nome_cliente = data.get("nome_cliente") or ""
        telefone = data.get("telefone") or ""

        # --- valor (taxa, renovação ou isento)
        valueType = (data.get("valueType") or data.get("valor") or "").lower()
        valor = ""
        if valueType == "taxa":
            valor = data.get("taxValue") or ""
        elif valueType == "renovacao":
            valor = "Isento mediante a renovação da fidelidade"

        scheduledDate = data.get("scheduledDate")
        period = data.get("period") or data.get("periodo") or ""
        data_str = format_date_br_with_time(scheduledDate, period)

        # --- melhor horário/reserva
        melhor_horario_reserva = (
            data.get("melhor_horario_reserva")
            or data.get("melhor_horario_agenda")
            or data.get("melhor_horario")
            or data.get("periodo_letra")
            or ""
        )

        # Normaliza para as letras esperadas pelo IXC: M / T / N / Q
        _map_mh = {
            "manha": "M", "manhã": "M", "m": "M",
            "tarde": "T", "t": "T",
            "noite": "N", "n": "N",
            "comercial": "Q", "comercialmente": "Q",
            "q": "Q",
            "": "Q"
        }

        mh_key = str(melhor_horario_reserva).strip().lower()
        if mh_key.upper() in ("M", "T", "N", "Q"):
            melhor_horario_agenda_val = mh_key.upper()
        else:
            melhor_horario_agenda_val = _map_mh.get(mh_key, _map_mh.get(mh_key.replace("ã", "a"), "Q"))

        # Dados específicos da mudança de ponto
        observacoes = data.get("observacoes") or data.get("observacao") or ""

        # 1) obter id_login
        id_login, err_login = get_login_id(id_contrato)
        if err_login:
            return jsonify({"error": err_login}), 400

        # --- formatar data e período
        date_display = ""
        if scheduledDate:
            try:
                date_part = str(scheduledDate).split("T")[0].split(" ")[0]
                dt = datetime.strptime(date_part, "%Y-%m-%d")
                date_display = dt.strftime("%d/%m/%Y")
            except Exception:
                date_display = str(scheduledDate)

        period_map = {"comercial": "Comercial", "manha": "Manhã", "tarde": "Tarde"}
        period_display = period_map.get((period or "").lower(), (period or "").capitalize())

        # 2) criar ticket com a mensagem específica EXATA
        mensagem = f"""CONFIGURAÇÃO DE ROTEADOR - PRIORIZAR PERÍODO INDICADO

Nome do contato: {nome_cliente}
Tel: {telefone}
Data/Período: {date_display} - {period_display}
Motivo do Agendamento: {observacoes}""".strip()

        id_tecnico_TICKET = str(data.get("id_responsavel_tecnico") or "147")

        resp_proto = requests.post(f"{HOST}/gerar_protocolo_atendimento", headers={**HEADERS, "ixcsoft": "inserir"}, timeout=30)
        protocoloAtendimento = resp_proto.text

        payload_ticket = {
            "tipo": "C",
            "protocolo": protocoloAtendimento,
            "id_cliente": id_cliente,
            "id_login": id_login,
            "id_contrato": id_contrato,
            "menssagem": mensagem,
            "id_responsavel_tecnico": id_tecnico_TICKET,
            "melhor_horario_reserva": melhor_horario_agenda_val,
            "id_resposta": "231",
            "id_ticket_origem": "I",
            "id_assunto": "168",
            "origem_endereco": "CC",
            "titulo": "Configuração de Roteador",
            "su_status": "AG",
            "id_ticket_setor": "3",
            "prioridade": "M",
            "id_wfl_processo": "8",
            "setor": "3",
            "id_wfl_processo": "132"
        }

        resp_ticket = requests.post(f"{HOST}/su_ticket", headers=HEADERS, data=json.dumps(payload_ticket), timeout=30)
        if resp_ticket.status_code != 200:
            return jsonify({"error": f"Erro ao criar ticket: {resp_ticket.status_code} - {resp_ticket.text}"}), 400
        ticket_data = resp_ticket.json()
        id_ticket = ticket_data.get("id")

        # 3) buscar OS para pegar o PROTOCOLO
        payload_busca_os = {"qtype": "id_ticket", "query": id_ticket, "oper": "=", "page": "1", "rp": "1"}
        resp_os_busca = requests.post(f"{HOST}/su_oss_chamado", headers={**HEADERS, "ixcsoft": "listar"}, data=json.dumps(payload_busca_os), timeout=30)
        os_data = resp_os_busca.json()
        if str(os_data.get("total", 0)) == "0":
            return jsonify({"error": "Nenhuma OS encontrada para o ticket criado."}), 400
        
        id_os = os_data["registros"][0]["id"]
        protocolo_os = os_data["registros"][0].get("protocolo", "")
        mensagem_atual = os_data["registros"][0].get("mensagem") or mensagem

        print(f"DEBUG: Protocolo da OS encontrado: {protocolo_os}")

        # 4) agendar OS com ID do assunto 259
        payload_agenda = {
            "tipo": "C",
            "id": id_os,
            "id_ticket": id_ticket,
            "id_cliente": id_cliente,
            "id_login": id_login,
            "id_contrato_kit": id_contrato,
            "id_tecnico": id_tecnico,
            "melhor_horario_agenda": melhor_horario_agenda_val,
            "status": "AG",
            "id_filial": 2,
            "id_assunto": 168,
            "setor": 1,
            "prioridade": "N",
            "origem_endereco": "CC",
            "mensagem_resposta": "Agendado via API - Configuração de Roteador",
            "data_agenda": data_str,
            "data_agenda_final": data_str,
            "mensagem": mensagem_atual
        }

        # ---- chamar su_oss_chamado_alterar_setor para garantir status/setor ----
        alterar_url = f"{HOST}/su_oss_chamado_alterar_setor"
        data_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        alterar_payload = {
            "id_chamado": str(id_os),
            "id_setor": str(payload_agenda.get("setor", 1)),
            "id_tecnico": str(payload_agenda.get("id_tecnico") or id_tecnico or ""),
            "id_assunto": str(payload_agenda.get("id_assunto", "")),
            "mensagem": f"Agendado automaticamente pelo sistemas (Automação Marques).\n Atendente responsavel pelo agendamento: {id_tecnico_TICKET}",
            "status": "AG",
            "data": data_now,
            "id_evento": "",
            "latitude": "",
            "longitude": "",
            "gps_time": "",
            "id_ticket": str(id_ticket),
            "id_filial": str(payload_agenda.get("id_filial", 2))
        }
        headers_alterar = {**HEADERS, "Content-Type": "application/json"}

        success = False
        try:
            resp_alter_put = requests.put(alterar_url, headers=headers_alterar, data=json.dumps(alterar_payload), timeout=30)
            if resp_alter_put.status_code >= 200 and resp_alter_put.status_code < 300:
                success = True
            else:
                print(f"PUT su_oss_chamado_alterar_setor retornou status {resp_alter_put.status_code}: {resp_alter_put.text}")
        except Exception as e:
            print("Erro no PUT su_oss_chamado_alterar_setor:", e)

        if not success:
            try:
                resp_alter_post = requests.post(alterar_url, headers=headers_alterar, data=json.dumps(alterar_payload), timeout=30)
                if resp_alter_post.status_code >= 200 and resp_alter_post.status_code < 300:
                    success = True
                else:
                    print(f"POST su_oss_chamado_alterar_setor retornou status {resp_alter_post.status_code}: {resp_alter_post.text}")
            except Exception as e:
                print("Erro no POST su_oss_chamado_alterar_setor:", e)

        if not success:
            return jsonify({"error": "Erro ao aplicar alterar_setor (status/setor). Veja logs do servidor para detalhes."}), 400

        # ---- PUT detalhado para gravar dados completos ----
        resp_put = requests.put(f"{HOST}/su_oss_chamado/{id_os}", headers=HEADERS, data=json.dumps(payload_agenda), timeout=30)
        if resp_put.status_code != 200:
            return jsonify({"error": f"Erro ao agendar OS (PUT detalhado): {resp_put.status_code} - {resp_put.text}"}), 400

        return jsonify({
            "message": "Configuração de roteador agendada com sucesso!",
            "id_ticket": id_ticket,
            "id_os_mudanca": id_os,
            "protocolo_os": protocolo_os
        }), 200

    except Exception as e:
        print("EXCEPTION /api/config:", str(e))
        return jsonify({"error": str(e)}), 500

# --------------------------
# Endpoint dedicado para troca de equipamento
# --------------------------
@app.route("/api/troca", methods=["POST", "OPTIONS"])
def rota_troca():
    try:
        data = request.get_json() or {}

        id_cliente = data.get("clientId") or data.get("id_cliente")
        id_contrato = data.get("contractId") or data.get("id_contrato")
        if not id_cliente or not id_contrato:
            return jsonify({"error": "ID do cliente e contrato são obrigatórios."}), 400

        # Campos básicos
        id_tecnico = data.get("id_tecnico") or "147"
        nome_cliente = data.get("nome_cliente") or ""
        telefone = data.get("telefone") or ""

        # --- valor (taxa, renovação ou isento)
        valueType = (data.get("valueType") or data.get("valor") or "").lower()
        valor = ""
        if valueType == "taxa":
            valor = data.get("taxValue") or ""
        elif valueType == "renovacao":
            valor = "Isento mediante a renovação da fidelidade"

        scheduledDate = data.get("scheduledDate")
        period = data.get("period") or data.get("periodo") or ""
        data_str = format_date_br_with_time(scheduledDate, period)

        # --- melhor horário/reserva
        melhor_horario_reserva = (
            data.get("melhor_horario_reserva")
            or data.get("melhor_horario_agenda")
            or data.get("melhor_horario")
            or data.get("periodo_letra")
            or ""
        )

        # Normaliza para as letras esperadas pelo IXC: M / T / N / Q
        _map_mh = {
            "manha": "M", "manhã": "M", "m": "M",
            "tarde": "T", "t": "T",
            "noite": "N", "n": "N",
            "comercial": "Q", "comercialmente": "Q",
            "q": "Q",
            "": "Q"
        }

        mh_key = str(melhor_horario_reserva).strip().lower()
        if mh_key.upper() in ("M", "T", "N", "Q"):
            melhor_horario_agenda_val = mh_key.upper()
        else:
            melhor_horario_agenda_val = _map_mh.get(mh_key, _map_mh.get(mh_key.replace("ã", "a"), "Q"))

        # Dados específicos da mudança de ponto
        observacoes = data.get("observacoes") or data.get("observacao") or ""

        # 1) obter id_login
        id_login, err_login = get_login_id(id_contrato)
        if err_login:
            return jsonify({"error": err_login}), 400

        # --- formatar data e período
        date_display = ""
        if scheduledDate:
            try:
                date_part = str(scheduledDate).split("T")[0].split(" ")[0]
                dt = datetime.strptime(date_part, "%Y-%m-%d")
                date_display = dt.strftime("%d/%m/%Y")
            except Exception:
                date_display = str(scheduledDate)

        period_map = {"comercial": "Comercial", "manha": "Manhã", "tarde": "Tarde"}
        period_display = period_map.get((period or "").lower(), (period or "").capitalize())

        # 2) criar ticket com a mensagem específica EXATA
        mensagem = f"""TROCA DE EQUIPAMENTO - PRIORIZAR PERÍODO INDICADO

Nome do contato: {nome_cliente}
Tel: {telefone}
Data/Período: {date_display} - {period_display}
Motivo do Agendamento: {observacoes}""".strip()

        id_tecnico_TICKET = str(data.get("id_responsavel_tecnico") or "147")

        resp_proto = requests.post(f"{HOST}/gerar_protocolo_atendimento", headers={**HEADERS, "ixcsoft": "inserir"}, timeout=30)
        protocoloAtendimento = resp_proto.text

        payload_ticket = {
            "tipo": "C",
            "protocolo": protocoloAtendimento,
            "id_cliente": id_cliente,
            "id_login": id_login,
            "id_contrato": id_contrato,
            "menssagem": mensagem,
            "id_responsavel_tecnico": id_tecnico_TICKET,
            "melhor_horario_reserva": melhor_horario_agenda_val,
            "id_resposta": "222",
            "id_ticket_origem": "I",
            "id_assunto": "176",
            "origem_endereco": "CC",
            "titulo": "Troca de Equipamento",
            "su_status": "AG",
            "id_ticket_setor": "3",
            "prioridade": "M",
            "id_wfl_processo": "8",
            "setor": "3",
            "id_wfl_processo": "126"
        }

        resp_ticket = requests.post(f"{HOST}/su_ticket", headers=HEADERS, data=json.dumps(payload_ticket), timeout=30)
        if resp_ticket.status_code != 200:
            return jsonify({"error": f"Erro ao criar ticket: {resp_ticket.status_code} - {resp_ticket.text}"}), 400
        ticket_data = resp_ticket.json()
        id_ticket = ticket_data.get("id")

        # 3) buscar OS para pegar o PROTOCOLO
        payload_busca_os = {"qtype": "id_ticket", "query": id_ticket, "oper": "=", "page": "1", "rp": "1"}
        resp_os_busca = requests.post(f"{HOST}/su_oss_chamado", headers={**HEADERS, "ixcsoft": "listar"}, data=json.dumps(payload_busca_os), timeout=30)
        os_data = resp_os_busca.json()
        if str(os_data.get("total", 0)) == "0":
            return jsonify({"error": "Nenhuma OS encontrada para o ticket criado."}), 400
        
        id_os = os_data["registros"][0]["id"]
        protocolo_os = os_data["registros"][0].get("protocolo", "")
        mensagem_atual = os_data["registros"][0].get("mensagem") or mensagem

        print(f"DEBUG: Protocolo da OS encontrado: {protocolo_os}")

        # 4) agendar OS com ID do assunto 259
        payload_agenda = {
            "tipo": "C",
            "id": id_os,
            "id_ticket": id_ticket,
            "id_cliente": id_cliente,
            "id_login": id_login,
            "id_contrato_kit": id_contrato,
            "id_tecnico": id_tecnico,
            "melhor_horario_agenda": melhor_horario_agenda_val,
            "status": "AG",
            "id_filial": 2,
            "id_assunto": 176,
            "setor": 1,
            "prioridade": "N",
            "origem_endereco": "CC",
            "mensagem_resposta": "Agendado via API - Troca de Equipamento",
            "data_agenda": data_str,
            "data_agenda_final": data_str,
            "mensagem": mensagem_atual
        }

        # ---- chamar su_oss_chamado_alterar_setor para garantir status/setor ----
        alterar_url = f"{HOST}/su_oss_chamado_alterar_setor"
        data_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        alterar_payload = {
            "id_chamado": str(id_os),
            "id_setor": str(payload_agenda.get("setor", 1)),
            "id_tecnico": str(payload_agenda.get("id_tecnico") or id_tecnico or ""),
            "id_assunto": str(payload_agenda.get("id_assunto", "")),
            "mensagem": f"Agendado automaticamente pelo sistemas (Automação Marques).\n Atendente responsavel pelo agendamento: {id_tecnico_TICKET}",
            "status": "AG",
            "data": data_now,
            "id_evento": "",
            "latitude": "",
            "longitude": "",
            "gps_time": "",
            "id_ticket": str(id_ticket),
            "id_filial": str(payload_agenda.get("id_filial", 2))
        }
        headers_alterar = {**HEADERS, "Content-Type": "application/json"}

        success = False
        try:
            resp_alter_put = requests.put(alterar_url, headers=headers_alterar, data=json.dumps(alterar_payload), timeout=30)
            if resp_alter_put.status_code >= 200 and resp_alter_put.status_code < 300:
                success = True
            else:
                print(f"PUT su_oss_chamado_alterar_setor retornou status {resp_alter_put.status_code}: {resp_alter_put.text}")
        except Exception as e:
            print("Erro no PUT su_oss_chamado_alterar_setor:", e)

        if not success:
            try:
                resp_alter_post = requests.post(alterar_url, headers=headers_alterar, data=json.dumps(alterar_payload), timeout=30)
                if resp_alter_post.status_code >= 200 and resp_alter_post.status_code < 300:
                    success = True
                else:
                    print(f"POST su_oss_chamado_alterar_setor retornou status {resp_alter_post.status_code}: {resp_alter_post.text}")
            except Exception as e:
                print("Erro no POST su_oss_chamado_alterar_setor:", e)

        if not success:
            return jsonify({"error": "Erro ao aplicar alterar_setor (status/setor). Veja logs do servidor para detalhes."}), 400

        # ---- PUT detalhado para gravar dados completos ----
        resp_put = requests.put(f"{HOST}/su_oss_chamado/{id_os}", headers=HEADERS, data=json.dumps(payload_agenda), timeout=30)
        if resp_put.status_code != 200:
            return jsonify({"error": f"Erro ao agendar OS (PUT detalhado): {resp_put.status_code} - {resp_put.text}"}), 400

        return jsonify({
            "message": "Troca de equipamento agendada com sucesso!",
            "id_ticket": id_ticket,
            "id_os_mudanca": id_os,
            "protocolo_os": protocolo_os
        }), 200

    except Exception as e:
        print("EXCEPTION /api/troca:", str(e))
        return jsonify({"error": str(e)}), 500

# --------------------------
# Endpoint dedicado para alarmada
# --------------------------
@app.route("/api/alarmada", methods=["POST", "OPTIONS"])
def rota_alarmada():
    try:
        data = request.get_json() or {}

        id_cliente = data.get("clientId") or data.get("id_cliente")
        id_contrato = data.get("contractId") or data.get("id_contrato")
        if not id_cliente or not id_contrato:
            return jsonify({"error": "ID do cliente e contrato são obrigatórios."}), 400

        # Campos básicos
        id_tecnico = data.get("id_tecnico") or "147"
        nome_cliente = data.get("nome_cliente") or ""
        telefone = data.get("telefone") or ""

        # --- valor (taxa, renovação ou isento)
        valueType = (data.get("valueType") or data.get("valor") or "").lower()
        valor = ""
        if valueType == "taxa":
            valor = data.get("taxValue") or ""
        elif valueType == "renovacao":
            valor = "Isento mediante a renovação da fidelidade"

        scheduledDate = data.get("scheduledDate")
        period = data.get("period") or data.get("periodo") or ""
        data_str = format_date_br_with_time(scheduledDate, period)

        # --- melhor horário/reserva
        melhor_horario_reserva = (
            data.get("melhor_horario_reserva")
            or data.get("melhor_horario_agenda")
            or data.get("melhor_horario")
            or data.get("periodo_letra")
            or ""
        )

        # Normaliza para as letras esperadas pelo IXC: M / T / N / Q
        _map_mh = {
            "manha": "M", "manhã": "M", "m": "M",
            "tarde": "T", "t": "T",
            "noite": "N", "n": "N",
            "comercial": "Q", "comercialmente": "Q",
            "q": "Q",
            "": "Q"
        }

        mh_key = str(melhor_horario_reserva).strip().lower()
        if mh_key.upper() in ("M", "T", "N", "Q"):
            melhor_horario_agenda_val = mh_key.upper()
        else:
            melhor_horario_agenda_val = _map_mh.get(mh_key, _map_mh.get(mh_key.replace("ã", "a"), "Q"))

        # Dados específicos da mudança de ponto
        observacoes = data.get("observacoes") or data.get("observacao") or ""

        # 1) obter id_login
        id_login, err_login = get_login_id(id_contrato)
        if err_login:
            return jsonify({"error": err_login}), 400

        # --- formatar data e período
        date_display = ""
        if scheduledDate:
            try:
                date_part = str(scheduledDate).split("T")[0].split(" ")[0]
                dt = datetime.strptime(date_part, "%Y-%m-%d")
                date_display = dt.strftime("%d/%m/%Y")
            except Exception:
                date_display = str(scheduledDate)

        period_map = {"comercial": "Comercial", "manha": "Manhã", "tarde": "Tarde"}
        period_display = period_map.get((period or "").lower(), (period or "").capitalize())

        # 2) criar ticket com a mensagem específica EXATA
        mensagem = f"""ONU ALARMADA - PRIORIZAR PERÍODO INDICADO

Nome do contato: {nome_cliente}
Tel: {telefone}
Data/Período: {date_display} - {period_display}
Motivo do Agendamento: {observacoes}""".strip()

        id_tecnico_TICKET = str(data.get("id_responsavel_tecnico") or "147")

        resp_proto = requests.post(f"{HOST}/gerar_protocolo_atendimento", headers={**HEADERS, "ixcsoft": "inserir"}, timeout=30)
        protocoloAtendimento = resp_proto.text

        payload_ticket = {
            "tipo": "C",
            "protocolo": protocoloAtendimento,
            "id_cliente": id_cliente,
            "id_login": id_login,
            "id_contrato": id_contrato,
            "menssagem": mensagem,
            "id_responsavel_tecnico": id_tecnico_TICKET,
            "melhor_horario_reserva": melhor_horario_agenda_val,
            "id_resposta": "218",
            "id_ticket_origem": "I",
            "id_assunto": "170",
            "origem_endereco": "CC",
            "titulo": "ONU Alarmada",
            "su_status": "AG",
            "id_ticket_setor": "3",
            "prioridade": "M",
            "id_wfl_processo": "8",
            "setor": "3",
            "id_wfl_processo": "122"
        }

        resp_ticket = requests.post(f"{HOST}/su_ticket", headers=HEADERS, data=json.dumps(payload_ticket), timeout=30)
        if resp_ticket.status_code != 200:
            return jsonify({"error": f"Erro ao criar ticket: {resp_ticket.status_code} - {resp_ticket.text}"}), 400
        ticket_data = resp_ticket.json()
        id_ticket = ticket_data.get("id")

        # 3) buscar OS para pegar o PROTOCOLO
        payload_busca_os = {"qtype": "id_ticket", "query": id_ticket, "oper": "=", "page": "1", "rp": "1"}
        resp_os_busca = requests.post(f"{HOST}/su_oss_chamado", headers={**HEADERS, "ixcsoft": "listar"}, data=json.dumps(payload_busca_os), timeout=30)
        os_data = resp_os_busca.json()
        if str(os_data.get("total", 0)) == "0":
            return jsonify({"error": "Nenhuma OS encontrada para o ticket criado."}), 400
        
        id_os = os_data["registros"][0]["id"]
        protocolo_os = os_data["registros"][0].get("protocolo", "")
        mensagem_atual = os_data["registros"][0].get("mensagem") or mensagem

        print(f"DEBUG: Protocolo da OS encontrado: {protocolo_os}")

        # 4) agendar OS com ID do assunto 259
        payload_agenda = {
            "tipo": "C",
            "id": id_os,
            "id_ticket": id_ticket,
            "id_cliente": id_cliente,
            "id_login": id_login,
            "id_contrato_kit": id_contrato,
            "id_tecnico": id_tecnico,
            "melhor_horario_agenda": melhor_horario_agenda_val,
            "status": "AG",
            "id_filial": 2,
            "id_assunto": 170,
            "setor": 1,
            "prioridade": "N",
            "origem_endereco": "CC",
            "mensagem_resposta": "Agendado via API - ONU Alarmada",
            "data_agenda": data_str,
            "data_agenda_final": data_str,
            "mensagem": mensagem_atual
        }

        # ---- chamar su_oss_chamado_alterar_setor para garantir status/setor ----
        alterar_url = f"{HOST}/su_oss_chamado_alterar_setor"
        data_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        alterar_payload = {
            "id_chamado": str(id_os),
            "id_setor": str(payload_agenda.get("setor", 1)),
            "id_tecnico": str(payload_agenda.get("id_tecnico") or id_tecnico or ""),
            "id_assunto": str(payload_agenda.get("id_assunto", "")),
            "mensagem": f"Agendado automaticamente pelo sistemas (Automação Marques).\n Atendente responsavel pelo agendamento: {id_tecnico_TICKET}",
            "status": "AG",
            "data": data_now,
            "id_evento": "",
            "latitude": "",
            "longitude": "",
            "gps_time": "",
            "id_ticket": str(id_ticket),
            "id_filial": str(payload_agenda.get("id_filial", 2))
        }
        headers_alterar = {**HEADERS, "Content-Type": "application/json"}

        success = False
        try:
            resp_alter_put = requests.put(alterar_url, headers=headers_alterar, data=json.dumps(alterar_payload), timeout=30)
            if resp_alter_put.status_code >= 200 and resp_alter_put.status_code < 300:
                success = True
            else:
                print(f"PUT su_oss_chamado_alterar_setor retornou status {resp_alter_put.status_code}: {resp_alter_put.text}")
        except Exception as e:
            print("Erro no PUT su_oss_chamado_alterar_setor:", e)

        if not success:
            try:
                resp_alter_post = requests.post(alterar_url, headers=headers_alterar, data=json.dumps(alterar_payload), timeout=30)
                if resp_alter_post.status_code >= 200 and resp_alter_post.status_code < 300:
                    success = True
                else:
                    print(f"POST su_oss_chamado_alterar_setor retornou status {resp_alter_post.status_code}: {resp_alter_post.text}")
            except Exception as e:
                print("Erro no POST su_oss_chamado_alterar_setor:", e)

        if not success:
            return jsonify({"error": "Erro ao aplicar alterar_setor (status/setor). Veja logs do servidor para detalhes."}), 400

        # ---- PUT detalhado para gravar dados completos ----
        resp_put = requests.put(f"{HOST}/su_oss_chamado/{id_os}", headers=HEADERS, data=json.dumps(payload_agenda), timeout=30)
        if resp_put.status_code != 200:
            return jsonify({"error": f"Erro ao agendar OS (PUT detalhado): {resp_put.status_code} - {resp_put.text}"}), 400

        return jsonify({
            "message": "ONU Alarmada agendada com sucesso!",
            "id_ticket": id_ticket,
            "id_os_mudanca": id_os,
            "protocolo_os": protocolo_os
        }), 200

    except Exception as e:
        print("EXCEPTION /api/alarmada:", str(e))
        return jsonify({"error": str(e)}), 500

# --------------------------
# Execução
# --------------------------
if __name__ == "__main__":
    print("Running app with HOST_API:", HOST, "GEOCODE_ENABLED:", GEOCODE_ENABLED)
    app.run(host="0.0.0.0", port=5000, debug=True)
