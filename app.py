import asyncio
import json
import os
import urllib.parse
import edge_tts
from google import genai
from google.genai import types
from moviepy.editor import AudioFileClip, CompositeAudioClip, VideoFileClip
import requests

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

VIDEO_INPUT = "gameplay.mp4"
AUDIO_OUTPUT = "narracao_temp.mp3"
VIDEO_OUTPUT = "gameplay_narrado.mp4"
PASTA_SFX = "sfx"


def baixar_audio_meme(termo_busca):
  """Pesquisa e baixa o áudio do meme mais popular no Myinstants em tempo real."""
  os.makedirs(PASTA_SFX, exist_ok=True)
  termo_encoded = urllib.parse.quote(termo_busca)
  url_api = f"https://www.myinstants.com/api/v1/instants/?format=json&search={termo_encoded}"
  try:
    res = requests.get(url_api, timeout=10).json()
    if res.get("results"):
      url_audio = res["results"][0]["sound"]
      nome_limpo = termo_busca.lower().replace(" ", "_")
      caminho_local = os.path.join(PASTA_SFX, f"{nome_limpo}.mp3")
      conteudo = requests.get(url_audio, timeout=10).content
      with open(caminho_local, "wb") as f:
        f.write(conteudo)
      print(f"[SFX Online] Áudio baixado: {termo_busca} -> {caminho_local}")
      return caminho_local
  except Exception as e:
    print(f"[SFX Erro] Não foi possível buscar o som '{termo_busca}': {e}")
  return None


def analisar_gameplay(caminho_video):
  print("[1/4] Enviando vídeo para análise visual do Gemini...")
  video_file = client.files.upload(file=caminho_video)

  prompt = """
    Assista a este clipe de gameplay de futebol.
    Crie uma narração cômica e sarcástica em português comentando as jogadas e falhas.
    
    Retorne EXCLUSIVAMENTE um JSON estruturado no formato:
    {
      "texto_narracao": "Texto completo da narração em português.",
      "efeitos_sonoros": [
        {"tempo_segundos": 2.5, "busca_meme": "faustao errou"},
        {"tempo_segundos": 6.1, "busca_meme": "risada pica pau"}
      ]
    }
    Em 'busca_meme', sugira termos de memes ou sons curtos conhecidos da internet brasileira (ex: 'faustao errou', 'risada chaves', 'gol da alemanha', 'mola', 'pancada').
    """

  resposta = client.models.generate_content(
      model="gemini-2.5-flash",
      contents=[video_file, prompt],
      config=types.GenerateContentConfig(
          response_mime_type="application/json"
      ),
  )
  return json.loads(resposta.text)


async def gerar_audio_narrador(texto, caminho_saida_audio):
  print("[2/4] Sintetizando voz cômica do narrador via Edge-TTS...")
  comunicador = edge_tts.Communicate(
      text=texto, voice="pt-BR-AntonioNeural", rate="+14%", pitch="+5Hz"
  )
  await comunicador.save(caminho_saida_audio)


def renderizar_video_final(caminho_video, dados_json, caminho_audio_narracao):
  print("[3/4] Baixando memes da internet e sincronizando trilha de áudio...")
  clip_video = VideoFileClip(caminho_video)
  audio_narracao = AudioFileClip(caminho_audio_narracao)
  audio_original = (
      clip_video.audio.volumex(0.20) if clip_video.audio else None
  )

  faixas_audio = []
  if audio_original:
    faixas_audio.append(audio_original)
  faixas_audio.append(audio_narracao)

  for item in dados_json.get("efeitos_sonoros", []):
    termo = item.get("busca_meme")
    tempo = item.get("tempo_segundos")
    if termo and tempo is not None:
      caminho_sfx = baixar_audio_meme(termo)
      if caminho_sfx and os.path.exists(caminho_sfx):
        try:
          som = AudioFileClip(caminho_sfx).set_start(tempo)
          faixas_audio.append(som)
        except Exception as err:
          print(f"Erro ao inserir áudio {caminho_sfx}: {err}")

  audio_final = CompositeAudioClip(faixas_audio)
  video_final = clip_video.set_audio(audio_final)

  print("[4/4] Renderizando arquivo MP4 final...")
  video_final.write_videofile(
      VIDEO_OUTPUT, codec="libx264", audio_codec="aac", preset="ultrafast"
  )
  print(f"Processo concluído com sucesso: {VIDEO_OUTPUT}")


if __name__ == "__main__":
  if os.path.exists(VIDEO_INPUT):
    dados = analisar_gameplay(VIDEO_INPUT)
    asyncio.run(gerar_audio_narrador(dados["texto_narracao"], AUDIO_OUTPUT))
    renderizar_video_final(VIDEO_INPUT, dados, AUDIO_OUTPUT)
  else:
    print(f"Erro: O arquivo '{VIDEO_INPUT}' não foi encontrado na raiz.")
