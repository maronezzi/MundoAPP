import requests
import pandas as pd
import json
import time
import os
import re  # <--- NOVA IMPORTAÇÃO ESSENCIAL
from datetime import datetime
import ytmusicapi
from ytmusicapi import YTMusic
from dotenv import load_dotenv

# --- CARREGA VARIÁVEIS DE AMBIENTE (.env) ---
load_dotenv()

# --- CONFIGURAÇÕES ---
API_URL = os.getenv("RADIO_API_URL")
ENDPOINT_HISTORY = "/history"
ARQUIVO_IDS_PLAYLISTS = "meus_ids_playlists.json" 
ARQUIVO_LOG = "historico_atualizacoes.log"
ARQUIVO_HEADERS_TXT = "headers_secreto.txt"

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
    if os.path.exists(ARQUIVO_HEADERS_TXT):
        try:
            with open(ARQUIVO_HEADERS_TXT, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception as e:
            msg = f"Erro ao ler '{ARQUIVO_HEADERS_TXT}': {e}"
            print(f"⚠️ {msg}")
            registrar_log(msg, "ERROR")
            return None
    return None

def autenticar_ytm():
    arquivo_auth = "browser.json"
    yt = None
    
    if os.path.exists(arquivo_auth):
        try:
            yt = YTMusic(arquivo_auth)
        except Exception as e:
            msg = f"Arquivo '{arquivo_auth}' corrompido ou inválido: {e}"
            print(f"❌ {msg}")
            registrar_log(msg, "CRITICAL")
            exit(1)
    else:
        print(f"⚠️ Arquivo '{arquivo_auth}' não encontrado.")
        headers_raw = ler_headers_externos()
        
        if not headers_raw:
            msg = f"CRÍTICO: Crie o arquivo '{ARQUIVO_HEADERS_TXT}' com seus headers."
            print(f"🛑 {msg}")
            registrar_log(msg, "CRITICAL")
            exit(1)
            
        print("⚙️ Gerando arquivo de autenticação...")
        try:
            ytmusicapi.setup(filepath=arquivo_auth, headers_raw=headers_raw)
            yt = YTMusic(arquivo_auth)
            registrar_log(f"Arquivo '{arquivo_auth}' gerado com sucesso.", "INFO")
        except Exception as e:
            msg = f"Falha fatal ao gerar autenticação: {e}"
            print(f"❌ {msg}")
            registrar_log(msg, "CRITICAL")
            exit(1)

    print("⏳ Testando conectividade com YouTube Music...")
    try:
        yt.get_search_suggestions("test")
        print("✅ Conexão estabelecida e validada!")
        return yt
    except Exception as e:
        msg = f"FALHA DE CONEXÃO: {e}"
        print(f"🛑 {msg}")
        registrar_log(msg, "CRITICAL")
        exit(1)

# --- TRATAMENTO E LIMPEZA DE DADOS (NOVO) ---
def sanitizar_nome(texto):
    """
    Remove textos entre parênteses () ou colchetes [], 
    remove espaços duplos e caracteres invisíveis.
    Ex: 'Artist - Song (FAIXA ESPECIAL)' -> 'Artist - Song'
    """
    if not isinstance(texto, str):
        return ""
    # Regex: Encontra qualquer coisa entre ( ) ou [ ] e substitui por vazio
    texto_limpo = re.sub(r'\s*[\(\[].*?[\)\]]', '', texto)
    # Remove espaços extras que sobraram
    return " ".join(texto_limpo.split())

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
    
    # Previne erros se vier valores nulos
    df['artist'] = df['artist'].fillna('')
    df['title'] = df['title'].fillna('')

    df['played_at'] = pd.to_datetime(df['played_at'])
    
    # --- APLICAÇÃO DA CORREÇÃO ---
    # Limpamos o Artista e o Título individualmente antes de juntar
    df['clean_artist'] = df['artist'].apply(sanitizar_nome)
    df['clean_title'] = df['title'].apply(sanitizar_nome)
    
    # Cria a string de busca otimizada
    df['track_full'] = df['clean_artist'] + " " + df['clean_title']
    
    # Mantemos o ID local original para deduplicação lógica interna
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
        # Pega o programa mais frequente ou ignora se vazio
        mode_result = df['program'].mode()
        if not mode_result.empty:
            top_prog = mode_result[0]
            TITULOS_PLAYLISTS['programa'] = f"🎙️ No Ritmo de: {top_prog}"
            prog_df = df[df['program'] == top_prog].drop_duplicates(subset=['track_id_local'])
            playlists_content['programa'] = prog_df['track_full'].tolist()[:50]
        else:
            playlists_content['programa'] = []
    else:
        playlists_content['programa'] = []

    # 4. Dayparting (Manhã)
    df['hour'] = df['played_at'].dt.hour
    manha = df[(df['hour'] >= 6) & (df['hour'] <= 9)].drop_duplicates(subset=['track_id_local'])
    playlists_content['manha'] = manha['track_full'].tolist()[:50]

    # 5. Ouro da Casa
    # Para a contagem, usamos o ID original (com metadados) para garantir que seja a mesma música exata,
    # mas na hora de entregar a lista, pegamos a versão limpa ('track_full').
    top_tracks = df['track_id_local'].value_counts().head(50).index.tolist()
    
    # Recupera o nome limpo baseado no ID original
    musicas_ouro = []
    for track_id in top_tracks:
        # Pega a primeira ocorrência do nome limpo correspondente a esse ID sujo
        nome_limpo = df.loc[df['track_id_local'] == track_id, 'track_full'].iloc[0]
        musicas_ouro.append(nome_limpo)
        
    playlists_content['ouro'] = musicas_ouro

    return playlists_content

# --- GERENCIAMENTO YTM ---
def buscar_video_ids(ytmusic, lista_musicas):
    video_ids = []
    total = len(lista_musicas)
    print(f"🔎 Buscando IDs para {total} músicas (Nomes Higienizados)...")
    
    for i, query in enumerate(lista_musicas):
        # Pula queries vazias
        if not query.strip():
            continue
            
        try:
            # Busca focada apenas em músicas para maior precisão
            search_results = ytmusic.search(query, filter="songs")
            if search_results:
                video_ids.append(search_results[0]['videoId'])
                print(f"   [{i+1}/{total}] ✅ {query}")
            else:
                # Fallback: Tenta busca geral se filtro 'songs' falhar
                search_results = ytmusic.search(query)
                if search_results and 'videoId' in search_results[0]:
                    video_ids.append(search_results[0]['videoId'])
                    print(f"   [{i+1}/{total}] ⚠️ (Busca Geral) {query}")
                else:
                    print(f"   [{i+1}/{total}] ❌ Não encontrado: {query}")
            time.sleep(0.3) # Rate limit leve
        except Exception as e:
            msg_erro = f"Erro ao buscar {query}: {e}"
            print(f"   {msg_erro}")
            registrar_log(msg_erro, "ERROR")
            
    return video_ids

def encontrar_playlist_existente(ytmusic, titulo_alvo):
    print(f"🧐 Verificando se a playlist '{titulo_alvo}' já existe...")
    try:
        meus_playlists = ytmusic.get_library_playlists(limit=None)
        for pl in meus_playlists:
            if pl['title'] == titulo_alvo:
                return pl['playlistId']
    except Exception as e:
        print(f"Erro ao listar playlists: {e}")
        registrar_log(f"Erro ao listar playlists: {e}", "ERROR")
    return None

def limpar_e_adicionar(ytmusic, playlist_id, track_ids, titulo):
    sucesso = True
    try:
        playlist_info = ytmusic.get_playlist(playlist_id)
        tracks_atuais = playlist_info.get('tracks', [])
        
        if tracks_atuais:
            print(f"   🧹 Removendo {len(tracks_atuais)} faixas antigas...")
            # Remove em lotes se necessário, mas a lib geralmente lida bem
            ytmusic.remove_playlist_items(playlist_id, tracks_atuais)
            time.sleep(2)
    except Exception as e:
        msg_erro = f"Erro ao limpar playlist '{titulo}': {e}"
        print(f"   {msg_erro}")
        registrar_log(msg_erro, "ERROR")
        sucesso = False

    if track_ids:
        try:
            # Adiciona novos itens
            # Nota: A API do YTM as vezes falha com muitos itens de uma vez, 
            # mas 50 costuma ser seguro.
            ytmusic.add_playlist_items(playlist_id, track_ids)
            print(f"   ✨ Adicionadas {len(track_ids)} novas faixas em '{titulo}'.")
            registrar_log(f"Playlist '{titulo}' atualizada ({len(track_ids)} faixas).", "SUCCESS")
        except Exception as e:
            msg_erro = f"Erro ao adicionar faixas na playlist '{titulo}': {e}"
            print(f"   {msg_erro}")
            registrar_log(msg_erro, "ERROR")
            sucesso = False
    else:
        print("   Nenhuma faixa nova encontrada.")
    
    return sucesso

def gerenciar_playlist(ytmusic, chave_playlist, track_ids):
    titulo = TITULOS_PLAYLISTS.get(chave_playlist, "Radio Playlist")
    descricao = DESCRICOES_PLAYLISTS.get(chave_playlist, "") + f"\nÚltima atualização: {datetime.now().strftime('%d/%m/%Y %H:%M')}"

    playlist_id = encontrar_playlist_existente(ytmusic, titulo)

    if not playlist_id:
        print(f"🆕 Playlist não encontrada. Criando nova: {titulo}")
        try:
            playlist_id = ytmusic.create_playlist(title=titulo, description=descricao)
        except Exception as e:
            msg_erro = f"Erro fatal ao criar playlist '{titulo}': {e}"
            print(f"❌ {msg_erro}")
            
            if "401" in str(e) or "Unauthorized" in str(e):
                registrar_log(msg_erro, "CRITICAL")
                exit(1)
            
            registrar_log(msg_erro, "ERROR")
            return
    else:
        print(f"♻️ Playlist encontrada (ID: {playlist_id}). Atualizando...")
        try:
            ytmusic.edit_playlist(playlist_id, title=titulo, description=descricao)
        except Exception as e:
            msg_erro = f"Erro ao editar playlist '{titulo}': {e}"
            print(f"⚠️ {msg_erro}")
            
            if "401" in str(e) or "Unauthorized" in str(e):
                registrar_log(msg_erro, "CRITICAL")
                exit(1)
                
            registrar_log(msg_erro, "ERROR")

    limpar_e_adicionar(ytmusic, playlist_id, track_ids, titulo)

# --- MAIN ---
def main():
    try:
        registrar_log("--- Iniciando execução (Modo Otimizado Busca) ---", "START")
        
        if not os.path.exists(".env") and not os.environ.get("RADIO_API_URL"):
            print("⚠️ AVISO: .env não encontrado.")

        yt = autenticar_ytm()
        
        raw_data = get_radio_data(limit=600)
        if not raw_data:
            registrar_log("Nenhum dado recebido da API da rádio.", "WARNING")
            return

        df = process_data(raw_data)
        print(f"📊 Processado e Sanitizado: {len(df)} linhas.")

        conteudo_playlists = gerar_listas_musicas(df)

        for chave, lista_musicas in conteudo_playlists.items():
            if not lista_musicas: continue
            print(f"\n🎧 --- {TITULOS_PLAYLISTS.get(chave, chave)} ---")
            track_ids = buscar_video_ids(yt, lista_musicas)
            gerenciar_playlist(yt, chave, track_ids)

        print("\n✅ Processo finalizado com sucesso!")
        registrar_log("Processo finalizado.", "END")
    except SystemExit:
        # Já logado dentro da função que chamou exit()
        pass
    except Exception as e:
        msg_erro = f"Ocorreu um erro inesperado: {e}"
        print(f"\n💥 {msg_erro}")
        registrar_log(msg_erro, "CRITICAL")
        exit(1)

if __name__ == "__main__":
    main()