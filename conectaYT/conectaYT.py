import requests
import pandas as pd
import json
import time
import os
from datetime import datetime
import ytmusicapi
from ytmusicapi import YTMusic
from dotenv import load_dotenv

# --- CARREGA VARIÁVEIS DE AMBIENTE (.env) ---
load_dotenv()

# --- CONFIGURAÇÕES ---
# A URL agora vem do arquivo .env. Se não existir, tenta o padrão ou falha.
API_URL = os.getenv("RADIO_API_URL")
ENDPOINT_HISTORY = "/history"
ARQUIVO_IDS_PLAYLISTS = "meus_ids_playlists.json" 
ARQUIVO_LOG = "historico_atualizacoes.log"
ARQUIVO_HEADERS_TXT = "headers_secreto.txt" # Arquivo de texto puro com os headers

# Nomes das Playlists
TITULOS_PLAYLISTS = {
    "apostas": "📻 Apostas da Rádio (Hidden Gems)",
    "gigantes": "🚀 As Gigantes do Streaming",
    "programa": "🎙️ No Ritmo do Programa",
    "manha": "☕ Café da Manhã na Rádio",
    "ouro": "🏆 Ouro da Casa (Top Rotation)"
}

DESCRICOES_PLAYLISTS = {
    "apostas": "Músicas que tocam na rádio mas ainda não estouraram no algoritmo.",
    "gigantes": "Os maiores sucessos que tocaram nas últimas 24h.",
    "programa": "A curadoria especial do programa de maior destaque.",
    "manha": "A seleção perfeita para começar o dia, baseada no histórico das 06h às 09h.",
    "ouro": "As músicas que a rádio mais confia e repete."
}

# --- FUNÇÃO DE LOG ---
def registrar_log(mensagem, status="INFO"):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    linha_log = f"[{timestamp}] [{status}] {mensagem}\n"
    try:
        with open(ARQUIVO_LOG, "a", encoding="utf-8") as f:
            f.write(linha_log)
    except Exception as e:
        print(f"⚠️ Erro ao gravar log: {e}")

# --- YOUTUBE MUSIC (AUTENTICAÇÃO SEGURA) ---
def ler_headers_externos():
    """Lê o arquivo de texto que contém os headers brutos."""
    if os.path.exists(ARQUIVO_HEADERS_TXT):
        try:
            with open(ARQUIVO_HEADERS_TXT, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception as e:
            print(f"⚠️ Erro ao ler '{ARQUIVO_HEADERS_TXT}': {e}")
            return None
    return None

def autenticar_ytm():
    arquivo_auth = "browser.json"
    yt = None
    
    # 1. Tenta carregar o arquivo de autenticação já gerado
    if os.path.exists(arquivo_auth):
        try:
            yt = YTMusic(arquivo_auth)
        except Exception as e:
            msg = f"Arquivo '{arquivo_auth}' corrompido ou inválido: {e}"
            print(f"❌ {msg}")
            registrar_log(msg, "CRITICAL")
            exit(1)
    else:
        # 2. Se não existe browser.json, tenta gerar usando o arquivo secreto de texto
        print(f"⚠️ Arquivo '{arquivo_auth}' não encontrado.")
        
        headers_raw = ler_headers_externos()
        
        if not headers_raw:
            msg = f"CRÍTICO: Crie o arquivo '{ARQUIVO_HEADERS_TXT}' com seus headers ou gere o '{arquivo_auth}' localmente antes de rodar."
            print(f"🛑 {msg}")
            registrar_log(msg, "CRITICAL")
            exit(1)
            
        print("⚙️ Gerando arquivo de autenticação a partir de headers externos...")
        try:
            ytmusicapi.setup(filepath=arquivo_auth, headers_raw=headers_raw)
            yt = YTMusic(arquivo_auth)
            registrar_log(f"Arquivo '{arquivo_auth}' gerado com sucesso.", "INFO")
        except Exception as e:
            msg = f"Falha fatal ao gerar autenticação com os headers fornecidos: {e}"
            print(f"❌ {msg}")
            registrar_log(msg, "CRITICAL")
            exit(1)

    # 3. TESTE DE CONEXÃO OBRIGATÓRIO (Safety Check)
    print("⏳ Testando conectividade com YouTube Music...")
    try:
        # Faz uma busca leve apenas para validar o token
        yt.get_search_suggestions("test")
        print("✅ Conexão estabelecida e validada!")
        registrar_log("Conexão com API do YouTube Music validada com sucesso.", "SUCCESS")
        return yt
    except Exception as e:
        msg = f"FALHA DE CONEXÃO: O token pode estar expirado ou sem internet. Erro: {e}"
        print(f"🛑 {msg}")
        registrar_log(msg, "CRITICAL")
        print("⚠️ Abortando todo o processo para evitar erros em cascata.")
        exit(1)

# --- DADOS DA RÁDIO ---
def get_radio_data(limit=600):
    if not API_URL:
        msg = "URL da API não configurada. Verifique o arquivo .env"
        print(f"❌ {msg}")
        registrar_log(msg, "CRITICAL")
        exit(1)

    print("📡 Baixando dados da rádio...")
    try:
        response = requests.get(f"{API_URL}{ENDPOINT_HISTORY}", params={"limit": limit})
        response.raise_for_status()
        return response.json()
    except Exception as e:
        msg_erro = f"Erro na API da rádio: {e}"
        print(f"❌ {msg_erro}")
        registrar_log(msg_erro, "ERROR")
        return []

def process_data(data):
    if not data: return pd.DataFrame()
    df = pd.DataFrame(data)
    df['played_at'] = pd.to_datetime(df['played_at'])
    df['track_full'] = df['artist'] + " " + df['title']
    df['track_id_local'] = df['artist'] + " - " + df['title']
    return df

# --- LÓGICA DAS PLAYLISTS ---
def gerar_listas_musicas(df):
    playlists_content = {}
    
    # 1. Apostas (Pop < 45)
    apostas = df[df['popularity'] < 45].drop_duplicates(subset=['track_id_local'])
    playlists_content['apostas'] = apostas['track_full'].tolist()[:50]

    # 2. Gigantes (Pop > 80)
    gigantes = df[df['popularity'] > 80].drop_duplicates(subset=['track_id_local'])
    playlists_content['gigantes'] = gigantes['track_full'].tolist()[:50]

    # 3. Programa
    if 'program' in df.columns:
        top_prog = df['program'].mode()[0]
        TITULOS_PLAYLISTS['programa'] = f"🎙️ No Ritmo de: {top_prog}"
        prog_df = df[df['program'] == top_prog].drop_duplicates(subset=['track_id_local'])
        playlists_content['programa'] = prog_df['track_full'].tolist()[:50]
    else:
        playlists_content['programa'] = []

    # 4. Dayparting (Manhã)
    df['hour'] = df['played_at'].dt.hour
    manha = df[(df['hour'] >= 6) & (df['hour'] <= 9)].drop_duplicates(subset=['track_id_local'])
    playlists_content['manha'] = manha['track_full'].tolist()[:50]

    # 5. Ouro da Casa
    contagem = df['track_id_local'].value_counts().head(50).index.tolist()
    musicas_ouro = [t.replace(" - ", " ") for t in contagem]
    playlists_content['ouro'] = musicas_ouro

    return playlists_content

# --- GERENCIAMENTO YTM ---
def buscar_video_ids(ytmusic, lista_musicas):
    video_ids = []
    total = len(lista_musicas)
    print(f"🔎 Buscando IDs para {total} músicas...")
    
    for i, query in enumerate(lista_musicas):
        try:
            search_results = ytmusic.search(query, filter="songs")
            if search_results:
                video_ids.append(search_results[0]['videoId'])
                print(f"   [{i+1}/{total}] ✅ {query}")
            else:
                print(f"   [{i+1}/{total}] ❌ Não encontrado: {query}")
            time.sleep(0.5)
        except Exception as e:
            print(f"   Erro ao buscar {query}: {e}")
            
    return video_ids

def encontrar_playlist_existente(ytmusic, titulo_alvo):
    print(f"🧐 Verificando se a playlist '{titulo_alvo}' já existe na conta...")
    try:
        meus_playlists = ytmusic.get_library_playlists(limit=None)
        for pl in meus_playlists:
            if pl['title'] == titulo_alvo:
                return pl['playlistId']
    except Exception as e:
        print(f"Erro ao listar playlists: {e}")
        registrar_log(f"Erro ao listar playlists para '{titulo_alvo}': {e}", "ERROR")
    return None

def limpar_e_adicionar(ytmusic, playlist_id, track_ids, titulo):
    sucesso = True
    try:
        playlist_info = ytmusic.get_playlist(playlist_id)
        tracks_atuais = playlist_info.get('tracks', [])
        
        if tracks_atuais:
            print(f"   🧹 Removendo {len(tracks_atuais)} faixas antigas...")
            ytmusic.remove_playlist_items(playlist_id, tracks_atuais)
            time.sleep(2)
    except Exception as e:
        print(f"   Erro ao limpar playlist: {e}")
        registrar_log(f"Erro ao limpar playlist '{titulo}': {e}", "WARNING")
        sucesso = False

    if track_ids:
        try:
            ytmusic.add_playlist_items(playlist_id, track_ids)
            print(f"   ✨ Adicionadas {len(track_ids)} novas faixas em '{titulo}'.")
            registrar_log(f"Playlist '{titulo}' atualizada com sucesso. ({len(track_ids)} faixas)", "SUCCESS")
        except Exception as e:
            print(f"   Erro ao adicionar faixas: {e}")
            registrar_log(f"Erro ao adicionar faixas na playlist '{titulo}': {e}", "ERROR")
            sucesso = False
    else:
        print("   Nenhuma faixa nova encontrada para adicionar.")
        registrar_log(f"Nenhuma faixa encontrada para playlist '{titulo}'.", "WARNING")
    
    return sucesso

def gerenciar_playlist(ytmusic, chave_playlist, track_ids):
    titulo = TITULOS_PLAYLISTS.get(chave_playlist, "Radio Playlist")
    descricao = DESCRICOES_PLAYLISTS.get(chave_playlist, "") + f"\nÚltima atualização: {datetime.now().strftime('%d/%m/%Y %H:%M')}"

    playlist_id = encontrar_playlist_existente(ytmusic, titulo)

    if not playlist_id:
        print(f"🆕 Playlist não encontrada. Criando nova: {titulo}")
        try:
            playlist_id = ytmusic.create_playlist(title=titulo, description=descricao)
            registrar_log(f"Nova playlist criada: {titulo}", "INFO")
        except Exception as e:
            msg_erro = f"Erro fatal ao criar playlist '{titulo}': {e}"
            print(f"❌ {msg_erro}")
            registrar_log(msg_erro, "ERROR")
            return
    else:
        print(f"♻️ Playlist encontrada (ID: {playlist_id}). Atualizando...")
        try:
            ytmusic.edit_playlist(playlist_id, title=titulo, description=descricao)
        except:
            pass

    limpar_e_adicionar(ytmusic, playlist_id, track_ids, titulo)

# --- MAIN ---

def main():
    registrar_log("--- Iniciando execução (Modo Seguro - GitHub Ready) ---", "START")
    
    # Validações iniciais de ambiente
    if not os.path.exists(".env") and not os.environ.get("RADIO_API_URL"):
        print("⚠️ AVISO: Arquivo .env não encontrado. Certifique-se de configurar as variáveis de ambiente.")

    # 1. Autenticação e Segurança
    yt = autenticar_ytm()
    
    # 2. Dados da Rádio
    raw_data = get_radio_data(limit=600)
    if not raw_data: 
        registrar_log("Dados da rádio vazios ou falha na API. Encerrando.", "ERROR")
        return

    df = process_data(raw_data)
    print(f"📊 Processado: {len(df)} linhas.")

    conteudo_playlists = gerar_listas_musicas(df)

    for chave, lista_musicas in conteudo_playlists.items():
        if not lista_musicas: continue
            
        print(f"\n🎧 --- {TITULOS_PLAYLISTS.get(chave)} ---")
        
        track_ids = buscar_video_ids(yt, lista_musicas)
        gerenciar_playlist(yt, chave, track_ids)

    print("\n✅ Processo finalizado com sucesso!")
    registrar_log("Processo finalizado com sucesso.", "END")

if __name__ == "__main__":
    main()