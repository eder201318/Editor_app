import os
import subprocess
import uuid
import time
import io
from flask import Flask, request, send_file, jsonify, render_template

# Configurações do Servidor
app = Flask(__name__, template_folder='.') # O Flask vai procurar o index.html na mesma pasta

UPLOAD_FOLDER = 'uploads'
PROCESSED_FOLDER = 'processed'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)

def verificar_ffmpeg():
    """Verifica se o FFmpeg está instalado no sistema."""
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except FileNotFoundError:
        return False

def limpar_arquivos_antigos():
    """Apaga ficheiros com mais de 5 minutos para poupar espaço e permitir o uso do IDM."""
    agora = time.time()
    for pasta in [UPLOAD_FOLDER, PROCESSED_FOLDER]:
        for ficheiro in os.listdir(pasta):
            caminho = os.path.join(pasta, ficheiro)
            if os.path.isfile(caminho):
                # st_mtime é a data de modificação do ficheiro. 300 segundos = 5 minutos
                if os.stat(caminho).st_mtime < agora - 300: 
                    try:
                        os.remove(caminho)
                        print(f"Limpeza automática: {ficheiro} apagado por inatividade (5 min).")
                    except Exception as e:
                        print(f"Erro ao apagar {ficheiro}: {e}")

def modificar_video(arquivo_entrada, arquivo_saida, config):
    """
    Constrói o comando do FFmpeg com base nas caixas de seleção do utilizador.
    """
    filtros_video_lista = []
    filtros_audio_lista = []
    
    # 1. Corte Inicial (Corta o primeiro 1 segundo)
    input_args = []
    if config.get('optCorte') == 'true':
        input_args.extend(["-ss", "1"]) # Pula 1 segundo logo na entrada para ser rápido
        
    input_args.extend(["-i", arquivo_entrada])

    # === FILTROS VISUAIS ===
    if config.get('optEspelhar') == 'true':
        filtros_video_lista.append("hflip")
        
    if config.get('optZoom') == 'true':
        filtros_video_lista.append("crop=iw*0.95:ih*0.95")
        
    if config.get('optCores') == 'true':
        filtros_video_lista.append("eq=brightness=0.02:saturation=1.05")

    # [NOVO] Rotação de Matiz (Altera subtilmente o espetro de cores em 2 graus)
    if config.get('optMatiz') == 'true':
        filtros_video_lista.append("hue=h=2")
        
    if config.get('optRuido') == 'true':
        filtros_video_lista.append("noise=alls=1:allf=t")

    # Rotação Milimétrica (1 grau)
    if config.get('optRotacao') == 'true':
        filtros_video_lista.append("rotate=1*PI/180")

    # Sobreposição "Fantasma" (Overlay 1% opacidade cor preta)
    if config.get('optFantasma') == 'true':
        filtros_video_lista.append("drawbox=x=0:y=0:w=iw:h=ih:color=black@0.01:t=fill")

    # Vinheta de Borda
    if config.get('optVinheta') == 'true':
        filtros_video_lista.append("vignette")

    # [NOVO] Mescla de Quadros (Frame Blending - Mistura frames para destruir a assinatura visual)
    if config.get('optMescla') == 'true':
        filtros_video_lista.append("tblend=all_mode=average")
        
    if config.get('optVelocidade') == 'true':
        filtros_video_lista.append("setpts=0.95*PTS")
        filtros_audio_lista.append("atempo=1.05")
    else:
        # Se não houver alteração de velocidade, garante que o áudio passa sem distorção
        filtros_audio_lista.append("volume=1.0")

    # === FILTROS DE ÁUDIO ===
    # Destruição de Frequências Extremas (Audio EQ)
    if config.get('optEQ') == 'true':
        filtros_audio_lista.append("highpass=f=80,lowpass=f=14000")

    # Pitch Shift Independente (Aumenta o tom ligeiramente)
    if config.get('optPitch') == 'true':
        filtros_audio_lista.append("asetrate=48000*1.03,atempo=1/1.03")

    # [NOVO] Micro-Eco / Reverb (Espalha as frequências no tempo)
    if config.get('optEco') == 'true':
        filtros_audio_lista.append("aecho=0.8:0.9:40:0.3")

    # [NOVO] Inversão de Canais de Áudio (Esquerda vai para a Direita e vice-versa)
    if config.get('optInversaoAudio') == 'true':
        filtros_audio_lista.append("pan=stereo|c0=c1|c1=c0")

    comando = ["ffmpeg"] + input_args

    # Camada de Áudio de Fundo (Misturar Ruído Branco/Marrom)
    if config.get('optAudioFundo') == 'true':
        # Gera ruído marrom com 1.5% de volume
        comando.extend(["-f", "lavfi", "-i", "anoisesrc=color=brown:amplitude=0.015"])
        
        # Como temos dois áudios (vídeo + ruído), usamos o filter_complex para os misturar (amix)
        v_filter = ",".join(filtros_video_lista) if filtros_video_lista else "null"
        a_filter = ",".join(filtros_audio_lista) if filtros_audio_lista else "anull"
        
        filter_complex = f"[0:v]{v_filter}[vout];[0:a]{a_filter}[a0];[a0][1:a]amix=inputs=2:duration=first[aout]"
        comando.extend(["-filter_complex", filter_complex, "-map", "[vout]", "-map", "[aout]"])
    else:
        # Modo simples caso não precise misturar áudios
        if filtros_video_lista:
            comando.extend(["-vf", ",".join(filtros_video_lista)])
        if filtros_audio_lista:
            comando.extend(["-af", ",".join(filtros_audio_lista)])

    # Argumentos de renderização de saída
    output_args = [
        "-c:v", "libx264",     # Codec de vídeo
        "-preset", "fast",     # Velocidade de renderização equilibrada
        "-crf", "23",          # Qualidade visual excelente
        "-c:a", "aac",         # Codec de áudio padrão
        "-b:a", "192k",        # Qualidade de áudio a 192kbps
    ]

    # Limpeza de Metadados
    if config.get('optMetadados') == 'true':
        output_args.extend(["-map_metadata", "-1"])

    # Alteração de FPS
    if config.get('optFPS') == 'true':
        output_args.extend(["-r", "29.5"])

    # Adiciona ficheiro de saída
    output_args.extend(["-y", arquivo_saida])
    comando.extend(output_args)

    try:
        # Executa o processamento do vídeo
        subprocess.run(comando, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Erro no FFmpeg: {e.stderr.decode('utf-8')}")
        return False

# ROTA 1: Página inicial
@app.route('/')
def index():
    if not verificar_ffmpeg():
        return "Erro Crítico: O FFmpeg não está instalado ou configurado no PATH do servidor.", 500
    return render_template('index.html')

# ROTA 2: Receção e processamento do vídeo
@app.route('/processar', methods=['POST'])
def processar():
    # Executa a limpeza de ficheiros antigos antes de processar um novo
    limpar_arquivos_antigos()

    if 'video' not in request.files:
        return jsonify({'erro': 'Nenhum vídeo enviado'}), 400
    
    arquivo = request.files['video']
    if arquivo.filename == '':
        return jsonify({'erro': 'Nenhum ficheiro selecionado'}), 400

    # Gera um identificador único para este trabalho
    id_unico = str(uuid.uuid4())
    extensao = ".mp4"
    
    caminho_entrada = os.path.join(UPLOAD_FOLDER, f"entrada_{id_unico}{extensao}")
    caminho_saida = os.path.join(PROCESSED_FOLDER, f"pronto_{id_unico}{extensao}")

    # Guarda o ficheiro original no servidor
    arquivo.save(caminho_entrada)

    # Extrai o estado das opções selecionadas (Checkboxes) do formulário HTML
    opcoes = request.form

    # Inicia o processo de alteração anti-bloqueio
    sucesso = modificar_video(caminho_entrada, caminho_saida, opcoes)

    # Apaga o vídeo original de imediato para poupar espaço (já não precisamos dele)
    if os.path.exists(caminho_entrada):
        os.remove(caminho_entrada)

    if sucesso:
        return jsonify({'sucesso': True, 'download_url': f'/download/{id_unico}'})
    else:
        return jsonify({'erro': 'Erro ao processar o vídeo no servidor.'}), 500

# ROTA 3: Transferência do vídeo pronto (Compatível com Gestores de Transferência como IDM)
@app.route('/download/<id_unico>')
def download(id_unico):
    caminho_saida = os.path.join(PROCESSED_FOLDER, f"pronto_{id_unico}.mp4")
    
    if os.path.exists(caminho_saida):
        # GERA UM NOME ÚNICO: Adiciona a timestamp (segundos atuais) ao nome do ficheiro
        nome_unico = f"video_blindado_{int(time.time())}.mp4"
        
        # Envia o vídeo diretamente do ficheiro físico (o IDM vai adorar isto)
        # O ficheiro será apagado automaticamente pela rotina de 5 minutos na próxima execução
        return send_file(
            caminho_saida, 
            as_attachment=True, 
            download_name=nome_unico, 
            mimetype='video/mp4'
        )
    else:
        return "Ficheiro não encontrado. O tempo limite de 5 minutos expirou.", 404

if __name__ == '__main__':
    print("="*50)
    print("   Iniciando o Servidor Web da Shorts Factory (IDM Compatible)...")
    print("   Aceda no seu navegador: http://127.0.0.1:5000")
    print("="*50)
    app.run(debug=True, port=5000)