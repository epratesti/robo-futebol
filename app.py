import asyncio
import json
import logging
import os
import re
import urllib.parse
import requests
from google import genai
from google.genai import types
from moviepy.editor import AudioFileClip, CompositeAudioClip, VideoFileClip
from pydub import AudioSegment
from pydub.effects import compress_dynamic_range, normalize

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VIDEO_INPUT = "gameplay.mp4"
AUDIO_OUTPUT = "narracao_temp.wav"
VIDEO_OUTPUT = "gameplay_narrado.mp4"
PASTA_SFX = "sfx"

NUMBERS_PT = {
    0: "zero", 1: "um", 2: "dois", 3: "três", 4: "quatro", 5: "cinco",
    6: "seis", 7: "sete", 8: "oito", 9: "nove", 10: "dez"
}


def expand_numbers_for_football(text: str) -> str:
  """Converte placares como '2x1' para 'dois a um' para leitura fluida."""

  def replace_score(match):
    left = NUMBERS_PT.get(int(match.group(1)), match.group(1))
    right = NUMBERS_PT.get(int(match.group(2)), match.group(2))
    return f"{left} a {right}"

  return re.sub(
      r"\b(\d{1,2})\s*x\s*(\d{1,2})\b",
      replace_score,
      text,
      flags=re.IGNORECASE,
  )


def natural_voice_text(text: str) -> str:
  text = text.replace("nao", "não").replace("que golaço", "que golaço!")
  return expand_numbers_for_football(text)


class VoiceGenerator:

  async def _edge_tts(self, text: str, output_path: str):
    import edge_tts

    communicate = edge_tts.Communicate(
        text, "pt-BR-AntonioNeural", rate="+14%", pitch="+5Hz"
    )
    await communicate.save(output_path)

  def _gtts(self, text: str, output_path: str):
    from gtts import gTTS

    tts = gTTS(text=text, lang="pt", slow=False)
    tts.save(output_path)

  def generate_segment(self, text: str, output_path: str):
    text_cleaned = natural_voice_text(text)
    providers = ["edge", "gtts"]
    for provider in providers:
      try:
        if provider == "edge":
          asyncio.run(self._edge_tts(text_cleaned, output_path))
        elif provider == "gtts":
          self._gtts(text_cleaned, output_path)

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
          return
      except Exception as e:
        logger.warning(f"Provedor {provider} falhou: {e}")
    raise RuntimeError("Todos os provedores de TTS falharam.")

  def polish_audio(self, input_path: str, output_path: str):
    """Aplica compressão e normalização de estúdio no áudio."""
    segment = AudioSegment.from_file(input_path)
    segment = segment.strip_silence(
        silence_len=180, silence_thresh=-42, padding=80
    )
    segment = compress_dynamic_range(
        segment, threshold=-18.0, ratio=2.2, attack=6.0, release=80.0
    )
    segment = normalize(segment, headroom=1.5)
    segment.export(output_path, format="wav")


def baixar_audio_meme(termo_busca: str):
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
      logger.info(f"[SFX] Baixado: {termo_busca} -> {caminho_local}")
      return caminho_local
  except Exception as e:
    logger.error(f"[SFX Erro] Falha ao buscar '{termo_busca}': {e}")
  return None


def analisar_gameplay(caminho_video: str):
  client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
  logger.info("[1/4] Enviando vídeo para o Gemini...")
  video_file = client.files.upload(file=caminho_video)

  prompt = """
    Assista a este clipe de futebol. Crie uma narração cômica e sarcástica em português.
    Retorne EXCLUSIVAMENTE um JSON no seguinte formato:
    {
      "texto_narracao": "Texto completo da narração em português.",
      "efeitos_sonoros": [
        {"tempo_segundos": 2.5, "busca_meme": "faustao errou"},
        {"tempo_segundos": 6.1, "busca_meme": "risada pica pau"}
      ]
    }
    """

  resposta = client.models.generate_content(
      model="gemini-2.5-flash",
      contents=[video_file, prompt],
      config=types.GenerateContentConfig(
          response_mime_type="application/json"
      ),
  )
  return json.loads(resposta.text)


def main():
  if not os.path.exists(VIDEO_INPUT):
    logger.error(f"Arquivo '{VIDEO_INPUT}' não encontrado!")
    return

  dados = analisar_gameplay(VIDEO_INPUT)

  logger.info("[2/4] Gerando áudio e aplicando pós-processamento...")
  temp_raw = "raw_narration.mp3"
  vg = VoiceGenerator()
  vg.generate_segment(dados["texto_narracao"], temp_raw)
  vg.polish_audio(temp_raw, AUDIO_OUTPUT)
  if os.path.exists(temp_raw):
    os.remove(temp_raw)

  logger.info("[3/4] Sincronizando vídeo, narração e memes...")
  clip_video = VideoFileClip(VIDEO_INPUT)
  audio_narracao = AudioFileClip(AUDIO_OUTPUT)
  audio_original = (
      clip_video.audio.volumex(0.20) if clip_video.audio else None
  )

  faixas_audio = []
  if audio_original:
    faixas_audio.append(audio_original)
  faixas_audio.append(audio_narracao)

  for item in dados.get("efeitos_sonoros", []):
    termo = item.get("busca_meme")
    tempo = item.get("tempo_segundos")
    if termo and tempo is not None:
      caminho_sfx = baixar_audio_meme(termo)
      if caminho_sfx and os.path.exists(caminho_sfx):
        try:
          som = AudioFileClip(caminho_sfx).set_start(tempo)
          faixas_audio.append(som)
        except Exception as err:
          logger.warning(f"Erro ao inserir SFX {caminho_sfx}: {err}")

  audio_final = CompositeAudioClip(faixas_audio)
  video_final = clip_video.set_audio(audio_final)

  logger.info("[4/4] Renderizando MP4 final...")
  video_final.write_videofile(
      VIDEO_OUTPUT, codec="libx264", audio_codec="aac", preset="ultrafast"
  )
  logger.info(f"Concluído! Arquivo gerado: {VIDEO_OUTPUT}")


if __name__ == "__main__":
  main()
