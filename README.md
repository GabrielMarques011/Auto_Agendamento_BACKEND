# 🚀 API de Agendamento Automático - Backend

> Sistema de integração com IXC Soft para automatização de transferências de endereço, criação de tickets e agendamento de ordens de serviço.

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-2.0+-green.svg)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📋 Índice

- [Sobre o Projeto](#-sobre-o-projeto)
- [Funcionalidades](#-funcionalidades)
- [Tecnologias](#-tecnologias)
- [Instalação](#-instalação)
- [Configuração](#-configuração)
- [Endpoints da API](#-endpoints-da-api)
- [Exemplos de Uso](#-exemplos-de-uso)
- [Estrutura do Projeto](#-estrutura-do-projeto)
- [Contribuindo](#-contribuindo)

---

## 🎯 Sobre o Projeto

Esta API Flask oferece uma interface robusta para integração com o sistema **IXC Soft**, permitindo automação completa de processos relacionados a:

- ✅ Consulta de clientes e contratos
- ✅ Busca de endereços via CEP
- ✅ Criação automática de tickets
- ✅ Agendamento de ordens de serviço
- ✅ Transferência de endereço com desativação de porta
- ✅ Atualização de dados contratuais com geolocalização

---

## ⚡ Funcionalidades

### 🔍 Consultas
- **Busca de CEP** com integração à API AwesomeAPI
- **Consulta de clientes** por CPF/CNPJ com fallbacks inteligentes
- **Listagem de contratos** por cliente ou ID

### 📝 Operações Automáticas
- **Criação de tickets** de transferência
- **Agendamento de OS** com data e período definidos
- **Geração de protocolo** de atendimento
- **Criação automática** de OS de desativação de porta

### 🗺️ Geolocalização
- Suporte a **latitude/longitude** via dados de CEP
- Fallback para **Geocoding Nominatim** (OpenStreetMap)
- Armazenamento de **código IBGE** da cidade

---

## 🛠️ Tecnologias

| Tecnologia | Versão | Descrição |
|------------|--------|-----------|
| **Python** | 3.8+ | Linguagem principal |
| **Flask** | 2.0+ | Framework web |
| **Flask-CORS** | - | Habilitação de CORS |
| **Requests** | - | Cliente HTTP |
| **Pandas** | - | Manipulação de datas |
| **python-dotenv** | - | Gerenciamento de variáveis de ambiente |

---

## 📦 Instalação

### Pré-requisitos

- Python 3.8 ou superior
- pip (gerenciador de pacotes Python)
- Credenciais de acesso à API do IXC Soft

### Passo a passo

```bash
# Clone o repositório
git clone https://github.com/GabrielMarques011/Auto_Agendamento_BACKEND.git

# Entre no diretório
cd Auto_Agendamento_BACKEND

# Crie um ambiente virtual
python -m venv venv

# Ative o ambiente virtual
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate

# Instale as dependências
pip install -r requirements.txt
```

### Arquivo `requirements.txt`

```txt
Flask==2.3.0
Flask-CORS==4.0.0
requests==2.31.0
python-dotenv==1.0.0
pandas==2.0.0
```

---

## ⚙️ Configuração

Crie um arquivo `.env` na raiz do projeto com as seguintes variáveis:

```env
# Credenciais IXC Soft (obrigatório)
TOKEN_API=seu_token_ixc_aqui
HOST_API=https://sua-url.ixcsoft.com.br/webservice/v1

# Geocoding (opcional)
GEOCODE_ENABLED=false
GEOCODE_USER_AGENT=my-app-geocoder/1.0
```

### Descrição das Variáveis

| Variável | Obrigatória | Descrição |
|----------|-------------|-----------|
| `TOKEN_API` | ✅ | Token de autenticação da API IXC |
| `HOST_API` | ✅ | URL base da API IXC (sem barra final) |
| `GEOCODE_ENABLED` | ❌ | Ativa geocoding via Nominatim (`true`/`false`) |
| `GEOCODE_USER_AGENT` | ❌ | User-agent para requisições de geocoding |

---

## 🌐 Endpoints da API

### 🔍 Consultas

#### `GET /api/cep/<cep>`
Busca informações de endereço por CEP.

**Exemplo de resposta:**
```json
{
  "cep": "01310-100",
  "address": "Avenida Paulista",
  "district": "Bela Vista",
  "city": "São Paulo",
  "state": "SP",
  "cityId": "3550308",
  "lat": "-23.5614",
  "lng": "-46.6564"
}
```

---

#### `POST /api/cliente`
Busca cliente por CPF, CNPJ ou ID.

**Payload:**
```json
{
  "query": "123.456.789-00",
  "qtype": "cnpj_cpf"
}
```

**Resposta:** Dados completos do cliente do IXC.

---

#### `POST /api/cliente_contrato`
Lista contratos de um cliente.

**Payload:**
```json
{
  "clientId": "12345",
  "page": "1",
  "rp": "50"
}
```

**Resposta:** Lista de contratos com paginação.

---

### 📝 Operações

#### `POST /api/transfer`
Realiza transferência completa de endereço.

**Payload completo:**
```json
{
  "clientId": "12345",
  "contractId": "67890",
  "nome_cliente": "João Silva",
  "telefone": "(11) 98765-4321",
  "valueType": "taxa",
  "taxValue": "150.00",
  "scheduledDate": "2025-10-20",
  "period": "tarde",
  
  "address": "Rua Nova",
  "number": "100",
  "neighborhood": "Centro",
  "cep": "01234-567",
  "city": "São Paulo",
  "complement": "Apto 12",
  "lat": "-23.5505",
  "lng": "-46.6333",
  "city_ibge": "3550308",
  
  "oldAddress": "Rua Antiga",
  "oldNumber": "50",
  "oldNeighborhood": "Jardim",
  "oldCep": "01234-000",
  "oldCity": "São Paulo",
  "portaNumber": "Porta 8 - OLT Centro",
  
  "id_tecnico": "147"
}
```

**O que faz:**
1. ✅ Valida ID do cliente e contrato
2. ✅ Obtém ID de login do contrato
3. ✅ Cria ticket de transferência
4. ✅ Agenda OS no novo endereço
5. ✅ Cria OS de desativação no endereço antigo
6. ✅ Atualiza dados do contrato (incluindo lat/lng)

**Resposta de sucesso:**
```json
{
  "message": "Transferência realizada com sucesso!",
  "id_ticket": "123456",
  "id_os_transferencia": "789012",
  "id_os_desativacao": "345678"
}
```

---

#### `POST /api/update_contrato`
Atualiza dados de endereço de um contrato.

**Payload:**
```json
{
  "contractId": "67890",
  "address": "Rua Atualizada",
  "number": "200",
  "neighborhood": "Novo Bairro",
  "cep": "12345-678",
  "city": "São Paulo",
  "state": "SP",
  "complement": "Casa 2",
  "lat": "-23.5505",
  "lng": "-46.6333",
  "city_ibge": "3550308"
}
```

**Funcionalidades:**
- ✅ Atualiza apenas campos enviados
- ✅ Valida e formata CEP automaticamente
- ✅ Mantém dados existentes não informados
- ✅ Suporte a geolocalização (lat/lng)

---

## 💡 Exemplos de Uso

### Exemplo 1: Buscar CEP e criar transferência

```javascript
// 1. Buscar dados do CEP
const cepData = await fetch('http://localhost:5000/api/cep/01310-100')
  .then(r => r.json());

// 2. Usar dados para transferência
const transfer = await fetch('http://localhost:5000/api/transfer', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    clientId: '12345',
    contractId: '67890',
    nome_cliente: 'João Silva',
    telefone: '(11) 98765-4321',
    scheduledDate: '2025-10-25',
    period: 'tarde',
    address: cepData.address,
    neighborhood: cepData.district,
    city: cepData.city,
    cep: cepData.cep,
    lat: cepData.lat,
    lng: cepData.lng,
    cityIbge: cepData.city_ibge,
    // ... demais campos
  })
}).then(r => r.json());
```

### Exemplo 2: Atualizar apenas endereço

```python
import requests

response = requests.post('http://localhost:5000/api/update_contrato', json={
    'contractId': '67890',
    'address': 'Rua Nova',
    'number': '100',
    'cep': '01234-567'
})

print(response.json())
```

---

## 📁 Estrutura do Projeto

```
Auto_Agendamento_BACKEND/
│
├── app.py                  # Aplicação principal
├── .env                    # Variáveis de ambiente (não commitar)
├── .env.example            # Exemplo de configuração
├── requirements.txt        # Dependências Python
├── README.md              # Este arquivo
│
└── venv/                  # Ambiente virtual (não commitar)
```

---

## 🚀 Executando o Projeto

```bash
# Com ambiente virtual ativado
python app.py
```

A API estará disponível em: **http://localhost:5000**

---

## 🔒 Segurança

⚠️ **Importante:**

- Nunca commite o arquivo `.env` com credenciais reais
- Use sempre HTTPS em produção
- Implemente rate limiting para endpoints públicos
- Valide e sanitize todos os inputs
- Configure CORS adequadamente para seu domínio

---

## 🤝 Contribuindo

Contribuições são bem-vindas! Para contribuir:

1. Faça um fork do projeto
2. Crie uma branch para sua feature (`git checkout -b feature/NovaFuncionalidade`)
3. Commit suas mudanças (`git commit -m 'Adiciona nova funcionalidade'`)
4. Push para a branch (`git push origin feature/NovaFuncionalidade`)
5. Abra um Pull Request

---

## 📝 Licença

Este projeto está sob a licença MIT. Veja o arquivo [LICENSE](LICENSE) para mais detalhes.

---

## 👨‍💻 Autor

**Gabriel Marques**

- GitHub: [@GabrielMarques011](https://github.com/GabrielMarques011)
- Repositório: [Auto_Agendamento_BACKEND](https://github.com/GabrielMarques011/Auto_Agendamento_BACKEND)

---

## 📞 Suporte

Para dúvidas ou problemas, abra uma [issue](https://github.com/GabrielMarques011/Auto_Agendamento_BACKEND/issues) no GitHub.

---

<div align="center">

**Desenvolvido com intuito de ajudar a equipe do Suporte, e assim automatizar processos na plataforma IXC Soft**

⭐ Se este projeto foi útil, deixe uma estrela no GitHub!

</div>
