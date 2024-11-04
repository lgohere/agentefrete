import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_tz, mktime_tz
import os
from dotenv import load_dotenv
import logging
from datetime import datetime, timedelta
import groq
import requests
import re
import json
import time

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Carregar variáveis de ambiente
load_dotenv()
USERNAME = os.getenv("EMAIL_USERNAME")
PASSWORD = os.getenv("EMAIL_PASSWORD")
IMAP_SERVER = "imap.uol.com.br"
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
QUALP_API_KEY = os.getenv("QUALP_API_KEY")

# Inicializar o cliente Groq
groq_client = groq.Groq(api_key=GROQ_API_KEY)

def connect_to_imap():
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(USERNAME, PASSWORD)
        logger.info("Login IMAP bem-sucedido")
        return mail
    except imaplib.IMAP4.error as e:
        logger.error(f"Erro de login IMAP: {e}")
        return None

def decode_subject(subject):
    decoded_parts = []
    for part, encoding in decode_header(subject):
        if isinstance(part, bytes):
            decoded_parts.append(part.decode(encoding or 'utf-8', errors='ignore'))
        else:
            decoded_parts.append(part)
    return ' '.join(decoded_parts)

def parse_groq_response(response):
    logger.info(f"Resposta bruta do GROQ:\n{response}")
    lines = response.strip().split('\n')
    data = {}
    
    for line in lines:
        logger.info(f"Processando linha: {line}")
        if ':' not in line:
            logger.warning(f"Linha sem ':' encontrada: {line}")
            continue
        
        key, value = [part.strip() for part in line.split(':', 1)]
        original_key = key
        key = key.lower().replace(' ', '_').replace('/', '_').replace('-', '_').lstrip('_-')
        
        logger.info(f"Chave original: '{original_key}', Chave processada: '{key}', Valor: '{value}'")
        
        if key == 'origem' or key == 'destino_estufagem':
            city_state = value.split()
            if len(city_state) >= 2:
                city = ' '.join(city_state[:-1])
                state = city_state[-1]
                data[key] = {'cidade': city, 'estado': state}
                logger.info(f"{key.capitalize()} capturado: {data[key]}")
            else:
                logger.warning(f"Formato de {key} inválido: {value}")
        elif key in ['espécie', 'especie']:
            data['especie'] = value
            logger.info(f"Espécie capturada: {data['especie']}")
        elif key == 'peso':
            number = re.search(r'\d+(?:[\.,]\d+)?', value)
            if number:
                data['peso'] = float(number.group().replace(',', '.'))
                logger.info(f"Peso capturado: {data['peso']}")
            else:
                logger.warning(f"Não foi possível extrair o peso de: {value}")
        elif key == 'volume':
            if value.lower() not in ['n/a', 'não fornecido', '(não fornecido)']:
                number = re.search(r'\d+(?:[\.,]\d+)?', value)
                if number:
                    data['volume'] = float(number.group().replace(',', '.'))
                    logger.info(f"Volume capturado: {data['volume']}")
                else:
                    logger.warning(f"Não foi possível extrair o volume de: {value}")
            else:
                data['volume'] = 0
                logger.info("Volume não fornecido, definido como 0")
        elif key == 'valor_da_mercadoria':
            if value.lower() not in ['n/a', 'não fornecido', '(não fornecido)']:
                number = re.search(r'\d+(?:[\.,]\d+)?', value)
                if number:
                    data['valor_da_mercadoria'] = float(number.group().replace(',', '.'))
                    logger.info(f"Valor da mercadoria capturado: {data['valor_da_mercadoria']}")
                else:
                    logger.warning(f"Não foi possível extrair o valor da mercadoria de: {value}")
            else:
                data['valor_da_mercadoria'] = 0
                logger.info("Valor da mercadoria não fornecido, definido como 0")
        elif key == 'eixos':
            number = re.search(r'\d+', value)
            if number:
                data['eixos_necessarios'] = int(number.group())
                logger.info(f"Eixos necessários capturados: {data['eixos_necessarios']}")
            else:
                data['eixos_necessarios'] = 5
                logger.info("Número de eixos não encontrado, definido como padrão (5)")
        else:
            logger.warning(f"Chave não reconhecida: {original_key}")

    logger.info(f"Dados parseados: {json.dumps(data, indent=2)}")

    # Renomear 'destino_estufagem' para 'destino'
    if 'destino_estufagem' in data:
        data['destino'] = data.pop('destino_estufagem')
        logger.info(f"Campo 'destino_estufagem' renomeado para 'destino': {data['destino']}")

    # Verificar se temos todas as informações necessárias
    required_fields = ['origem', 'destino', 'peso', 'eixos_necessarios']
    missing_fields = [field for field in required_fields if field not in data]
    
    if missing_fields:
        logger.error(f"Campos obrigatórios ausentes: {', '.join(missing_fields)}")
        return None
    else:
        logger.info("Todos os campos obrigatórios foram capturados com sucesso.")
        return data

def extract_email_content(mail, email_id):
    _, msg_data = mail.fetch(email_id, "(RFC822)")
    email_body = msg_data[0][1]
    email_message = email.message_from_bytes(email_body)
    
    if email_message.is_multipart():
        for part in email_message.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset()
                if charset is None:
                    # Se o charset não for especificado, tente algumas codificações comuns
                    for encoding in ['utf-8', 'latin-1', 'iso-8859-1']:
                        try:
                            return payload.decode(encoding)
                        except UnicodeDecodeError:
                            continue
                    # Se nenhuma codificação funcionar, use 'utf-8' com substituição de caracteres
                    return payload.decode('utf-8', errors='replace')
                else:
                    return payload.decode(charset)
    else:
        payload = email_message.get_payload(decode=True)
        charset = email_message.get_content_charset()
        if charset is None:
            # Se o charset não for especificado, tente algumas codificações comuns
            for encoding in ['utf-8', 'latin-1', 'iso-8859-1']:
                try:
                    return payload.decode(encoding)
                except UnicodeDecodeError:
                    continue
            # Se nenhuma codificação funcionar, use 'utf-8' com substituição de caracteres
            return payload.decode('utf-8', errors='replace')
        else:
            return payload.decode(charset)

    # Se não conseguir extrair o conteúdo, retorne uma string vazia
    return ""

def process_email_with_groq(email_content):
    prompt = f"""
    # RULE: YOU ARE COMPLETELY MUTED. DO NOT COMMENT OR EXPLAIN ANYTHING.

    Você é uma máquina inteligentíssima e muda. Completamente objetiva e concisa em suas ações sem nenhum comentário.
    Analise o seguinte conteúdo de e-mail de cotação de frete e extraia as informações relevantes para cálculo:

    IMPORTANTE: 
    {email_content}

    Forneça as seguintes informações:
    - Origem: (Apenas cidade e estado, ignorando bairros ou subdivisões. Ex: SAO PAULO SP)
    - Destino/Estufagem: (Apenas cidade e estado, ignorando bairros ou subdivisões. Ex: SANTOS SP)
    - Quantidade de Containers: (Ex: 1)
    - Espécie: (40'HC)
    - Peso: (number) kg
    - Volume: (number) m³
    - Valor da mercadoria: (number)
    - Eixos: (number)

    REGRAS IMPORTANTES:
    1. Para Origem e Destino, forneça APENAS o nome da cidade e o estado, sem incluir bairros ou subdivisões.
       Exemplo correto: "SAO VICENTE SP" em vez de "Humaitá - São Vicente SP"
    2. Com base no peso da carga, identifique a quantidade de eixos necessários para cada viagem, seguindo estas regras:
       - Cargas > 25 ton = 6 eixos
       - Cargas <= 25 ton = 5 eixos
       - Cargas <= 20 ton = 4 eixos
       - Cargas <= 12 ton = 3 eixos
       
    3. Caso sejam múltiplos containers, por exemplo 1x40'HC e 1x20'HC, faça cotações separadas sem multiplicar o valor da quantidade de containers pelo peso.
       Defina apenas a cotação de uma unidade.

    Lembre-se: Seja conciso e forneça apenas as informações solicitadas, sem explicações adicionais.
    """

    chat_completion = groq_client.chat.completions.create(
        messages=[
            {"role": "system", "content": "Você é um assistente especializado em extrair informações de e-mails de cotação de frete e calcular requisitos de transporte."},
            {"role": "user", "content": prompt}
        ],
        model="mixtral-8x7b-32768",
        temperature=0.2,
        max_tokens=1000
    )

    return chat_completion.choices[0].message.content

def parse_date(date_str):
    try:
        date_tuple = parsedate_tz(date_str)
        if date_tuple:
            return datetime.fromtimestamp(mktime_tz(date_tuple)).strftime("%d/%m/%Y %H:%M:%S")
    except Exception as e:
        logger.error(f"Erro ao analisar a data: {e}")
    return date_str

def calculate_freight_with_qualp(data):
    url = "https://api.qualp.com.br/rotas/v4"
    
    payload = {
        "locations": [
            f"{data['origem']['cidade']},{data['origem']['estado']}",
            f"{data['destino']['cidade']},{data['destino']['estado']}"
        ],
        "config": {
            "route": {
                "optimized_route": False,
                "optimized_route_destination": "last",
                "calculate_return": True,
                "alternative_routes": 0,
                "avoid_locations": True,
                "avoid_locations_key": "",
                "type_route": "efficient"
            },
            "vehicle": {
                "type": "truck",
                "axis": data['eixos_necessarios'],
                "top_speed": None
            },
            "tolls": {
                "retroactive_date": datetime.now().strftime("%d/%m/%Y")
            },
            "freight_table": {
                "category": "D",
                "freight_load": "conteineirizada",
                "axis": data['eixos_necessarios']
            },
            "fuel_consumption": {
                "fuel_price": None,
                "km_fuel": None
            },
            "private_places": {
                "max_distance_from_location_to_route": 1000,
                "categories": True,
                "areas": True,
                "contacts": True,
                "products": True,
                "services": True
            }
        },
        "show": {
            "tolls": True,
            "freight_table": True,
            "maneuvers": False,
            "truck_scales": True,
            "static_image": False,
            "link_to_qualp": True,
            "private_places": False,
            "polyline": False,
            "simplified_polyline": False,
            "ufs": False,
            "fuel_consumption": False,
            "link_to_qualp_report": False
        },
        "format": "json",
        "exception_key": ""
    }
    
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Access-Token': QUALP_API_KEY
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Erro ao calcular frete com Qualp API: {e}")
        logger.error(f"Resposta da API: {response.text}")
        return None

def format_freight_output(qualp_response, groq_data):
    output = []
    output.append("COTAÇÃO DE FRETE (IDA E VOLTA)")
    output.append("=" * 30)

    # Informações básicas
    output.append(f"Origem: {groq_data['origem']['cidade']}, {groq_data['origem']['estado']}")
    output.append(f"Destino: {groq_data['destino']['cidade']}, {groq_data['destino']['estado']}")
    output.append(f"Espécie: {groq_data['especie']}")
    output.append(f"Peso: {groq_data['peso']} kg")
    output.append(f"Eixos: {groq_data['eixos_necessarios']}")
    output.append("")

    # Informações da rota (ida e volta)
    output.append("DETALHES DA ROTA (IDA E VOLTA)")
    output.append("-" * 30)
    output.append(f"Distância total: {qualp_response['distancia']['texto']}")
    output.append(f"Duração total estimada: {qualp_response['duracao']['texto']}")
    output.append(f"Distância não pavimentada: {qualp_response['distancia_nao_pavimentada']['texto']} ({qualp_response['distancia_nao_pavimentada']['percentual_texto']})")
    output.append("")

    # Informações de custo
    output.append("CUSTOS (IDA E VOLTA)")
    output.append("-" * 30)
    frete = qualp_response['tabela_frete']['dados']['D'][str(groq_data['eixos_necessarios'])]['conteineirizada']
    output.append(f"Valor do frete (ida e volta): R$ {frete:.2f}")

    total_pedagio = sum(pedagio['tarifa'][str(groq_data['eixos_necessarios'])] for pedagio in qualp_response['pedagios'])
    output.append(f"Total de pedágios (ida e volta): R$ {total_pedagio:.2f}")
    output.append(f"Quantidade de pedágios (ida e volta): {len(qualp_response['pedagios'])}")
    output.append("")

    # Informações adicionais
    output.append("INFORMAÇÕES ADICIONAIS")
    output.append("-" * 30)
    output.append(f"Quantidade de balanças no percurso: {len(qualp_response['balancas'])}")
    output.append(f"Resolução ANTT: {qualp_response['tabela_frete']['antt_resolucao']['nome']}")
    output.append(f"Data da resolução: {qualp_response['tabela_frete']['antt_resolucao']['data']}")
    output.append(f"Link para visualização: {qualp_response['link_site_qualp']}")

    return "\n".join(output)

def check_most_recent_email(mail):
    """
    Monitora continuamente os e-mails que atendem aos critérios:
    - Tem 'COTA' no assunto
    - É de um remetente com '@br-asgroup.com'
    Processa apenas o e-mail mais recente que atende a esses critérios e não foi processado anteriormente.
    """
    last_processed_id = None

    while True:
        try:
            mail.select("INBOX")
            
            # Busca por e-mails que atendem aos critérios
            search_criteria = '(SUBJECT "COTA" FROM "@br-asgroup.com")'
            _, message_numbers = mail.search(None, search_criteria)
            email_ids = message_numbers[0].split()
            
            if not email_ids:
                logger.info("Nenhum e-mail encontrado que atenda aos critérios. Aguardando...")
                time.sleep(60)  # Espera 1 minuto antes de verificar novamente
                continue

            # Pega o ID do e-mail mais recente que atende aos critérios
            latest_email_id = email_ids[-1]
            
            if latest_email_id == last_processed_id:
                logger.info("Nenhum novo e-mail que atenda aos critérios desde a última verificação.")
                time.sleep(60)  # Espera 1 minuto antes de verificar novamente
                continue

            _, msg_data = mail.fetch(latest_email_id, "(BODY[HEADER.FIELDS (SUBJECT FROM)])")
            email_data = msg_data[0][1].decode('utf-8', errors='ignore')
            email_message = email.message_from_string(email_data)
            
            subject = decode_subject(email_message["Subject"])
            from_ = email_message["From"]
            
            logger.info(f"Novo e-mail encontrado que atende aos critérios.")
            logger.info(f"Assunto: {subject}")
            logger.info(f"De: {from_}")
            
            email_content = extract_email_content(mail, latest_email_id)
            logger.info("Conteúdo do e-mail capturado.")
            
            if email_content:
                groq_response = process_email_with_groq(email_content)
                logger.info(f"Resposta do Groq:\n{groq_response}")
                
                parsed_data = parse_groq_response(groq_response)
                if parsed_data:
                    logger.info(f"Dados extraídos e parseados:\n{json.dumps(parsed_data, indent=2)}")
                    
                    qualp_response = calculate_freight_with_qualp(parsed_data)
                    if qualp_response:
                        formatted_output = format_freight_output(qualp_response, parsed_data)
                        logger.info(f"Resultado formatado da cotação de frete:\n\n{formatted_output}")
                    else:
                        logger.warning("Não foi possível calcular o frete com a API Qualp.")
                else:
                    logger.error("Não foi possível processar a resposta do Groq.")
            else:
                logger.error("Não foi possível extrair o conteúdo do e-mail.")
            
            last_processed_id = latest_email_id
            logger.info("-" * 50)

        except Exception as e:
            logger.error(f"Erro ao processar o e-mail: {str(e)}")
            logger.exception("Detalhes do erro:")

        time.sleep(60)  # Espera 1 minuto antes de verificar novamente

def main():
    mail = connect_to_imap()
    if not mail:
        logger.error("Não foi possível conectar ao servidor de e-mail.")
        return

    try:
        logger.info("Iniciando monitoramento contínuo do e-mail mais recente.")
        check_most_recent_email(mail)
    except KeyboardInterrupt:
        logger.info("Monitoramento interrompido pelo usuário.")
    except Exception as e:
        logger.error(f"Erro inesperado: {e}")
    finally:
        mail.logout()
        logger.info("Sessão de e-mail encerrada.")

if __name__ == "__main__":
    main()