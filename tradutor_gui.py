import multiprocessing
multiprocessing.freeze_support()

import sys
import os

# Quando empacotado pelo PyInstaller, garante que o ffmpeg bundleado seja achado
if getattr(sys, 'frozen', False):
  _bundle_dir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
  os.environ['PATH'] = _bundle_dir + os.pathsep + os.environ.get('PATH', '')

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
import threading
import re
import sounddevice as sd
import numpy as np
from faster_whisper import WhisperModel
from deep_translator import GoogleTranslator
from pydub import AudioSegment
from io import BytesIO
import asyncio
import edge_tts


# =========================
#  Idiomas
# =========================
idiomas = {
  "🇧🇷 Português (Brasil)": "pt",
  "🇺🇸 Inglês": "en",
  "🇪🇸 Espanhol": "es",
  "🇫🇷 Francês": "fr",
  "🇩🇪 Alemão": "de",
  "🇮🇹 Italiano": "it",
  "🇯🇵 Japonês": "ja",
  "🇨🇳 Chinês (Mandarim)": "zh",
  "🇰🇷 Coreano": "ko",
  "🇷🇺 Russo": "ru",
  "🇦🇪 Árabe": "ar",
  "🇮🇱 Hebraico": "he",
  "🇮🇳 Hindi": "hi",
  "🇹🇷 Turco": "tr",
  "🇳🇱 Holandês": "nl",
  "🇵🇱 Polonês": "pl",
  "🇸🇪 Sueco": "sv",
  "🇳🇴 Norueguês": "no",
  "🇩🇰 Dinamarquês": "da",
  "🇫🇮 Finlandês": "fi",
  "🇬🇷 Grego": "el",
  "🇨🇿 Tcheco": "cs",
  "🇭🇺 Húngaro": "hu",
  "🇷🇴 Romeno": "ro",
  "🇺🇦 Ucraniano": "uk",
  "🇻🇳 Vietnamita": "vi",
  "🇹🇭 Tailandês": "th",
  "🇮🇩 Indonésio": "id",
  "🇭🇹 Crioulo haitiano": "ht",
}


# Códigos com mapeamento diferente entre Whisper e deep-translator
TRANSLATE_CODE_OVERRIDE = {
  "zh": "zh-CN",
  "he": "iw",
}

# Cache de tradutores por idioma destino — evita recriar a cada fala
_translators = {}
def get_translator(dest_code):
  if dest_code not in _translators:
      _translators[dest_code] = GoogleTranslator(source='auto', target=dest_code)
  return _translators[dest_code]


# =========================
#  Modelo Whisper (faster-whisper, quantizado int8 — mesma qualidade, ~3-4x mais rápido em CPU)
# =========================
modelo = WhisperModel("medium", device="cpu", compute_type="int8")
WHISPER_SR = 16000  # faster-whisper espera 16 kHz mono float32 quando se passa array


# =========================
#  Estado global
# =========================
gravacao = []
stream = None
ultima_pessoa = None
samplerate = 16000


# =========================
#  Utils de dispositivos
# =========================
def listar_dispositivos_unico():
  """Lista de dispositivos para um seletor único por pessoa.
  Inclui qualquer device com entrada de mic; marca com 🎧 quando também tem saída."""
  devices = sd.query_devices()
  hostapis = sd.query_hostapis()
  out = []
  for i, d in enumerate(devices):
      in_ch = d.get('max_input_channels', 0)
      if in_ch == 0:
          continue
      host = hostapis[d['hostapi']]['name'] if d['hostapi'] < len(hostapis) else "Host"
      label = f"[{i}] {d['name']}"
      out.append((label, i))
  return out


def label_para_index(label):
  try:
      m = re.search(r'\[(\d+)\]', label or "")
      if m:
          return int(m.group(1))
  except Exception:
      pass
  return None


def output_device_for(idx):
  """Se o device escolhido tiver saída, usa ele; senão cai no default do sistema."""
  try:
      if idx is not None:
          if sd.query_devices(idx).get('max_output_channels', 0) > 0:
              return idx
  except Exception:
      pass
  try:
      return sd.default.device[1]
  except Exception:
      return None


def sr_do_device(device_index, io_kind='input'):
  info = sd.query_devices(device_index)
  sr = info.get('default_samplerate', 48000 if io_kind=='output' else 16000) or (48000 if io_kind=='output' else 16000)
  return int(sr)


# =========================
#  Áudio: gravação
# =========================
def callback(indata, frames, time, status):
  if status:
      pass
  gravacao.append(indata.copy())


def iniciar_gravacao(pessoa, device_index):
  global gravacao, stream, ultima_pessoa, samplerate
  gravacao = []
  ultima_pessoa = pessoa


  if device_index is None:
      set_status("❌ Selecione um dispositivo válido.")
      return


  info_in = sd.query_devices(device_index)
  in_channels = 1 if info_in['max_input_channels'] >= 1 else info_in['max_input_channels']
  if in_channels < 1:
      set_status("❌ Este dispositivo não tem canal de entrada.")
      return


  samplerate = int(info_in.get('default_samplerate', 16000) or 16000)
  set_status(f"🎤 Gravando {pessoa}…")


  try:
      stream_args = dict(
          samplerate=samplerate, channels=1, device=device_index,
          callback=callback, dtype='float32', blocksize=0
      )
      globals()['stream'] = sd.InputStream(**stream_args)
      stream.start()
  except Exception as e:
      set_status(f"❌ Erro ao iniciar gravação: {e}")


# =========================
#  Áudio: TTS + reprodução
# =========================
async def falar_texto_edge(texto, idioma, out_device_index):
  if out_device_index is None:
      set_status("❌ Selecione uma saída/fone válido.")
      return


  idioma_voice_map = {
      "pt": "pt-BR-AntonioNeural",
      "en": "en-US-GuyNeural",
      "es": "es-ES-AlvaroNeural",
      "fr": "fr-FR-HenriNeural",
      "de": "de-DE-ConradNeural",
      "it": "it-IT-ElsaNeural",
      "ja": "ja-JP-NanamiNeural",
      "zh": "zh-CN-YunxiNeural",
      "ko": "ko-KR-InJoonNeural",
      "ru": "ru-RU-DmitryNeural",
      "ar": "ar-EG-SalmaNeural",
      "he": "he-IL-AvriNeural",
      "hi": "hi-IN-MadhurNeural",
      "tr": "tr-TR-AhmetNeural",
      "nl": "nl-NL-ColetteNeural",
      "pl": "pl-PL-MarekNeural",
      "sv": "sv-SE-MattiasNeural",
      "no": "nb-NO-FinnNeural",
      "da": "da-DK-JeppeNeural",
      "fi": "fi-FI-HarriNeural",
      "el": "el-GR-NestorasNeural",
      "cs": "cs-CZ-AntoninNeural",
      "hu": "hu-HU-TamasNeural",
      "ro": "ro-RO-EmilNeural",
      "uk": "uk-UA-OstapNeural",
      "vi": "vi-VN-NamMinhNeural",
      "th": "th-TH-NiwatNeural",
      "id": "id-ID-ArdiNeural",
      "ht": "fr-FR-HenriNeural",  # fallback
  }
  voz = idioma_voice_map.get(idioma, "en-US-GuyNeural")

  # Streamar MP3 do edge-tts direto pra memória (sem escrever em disco)
  audio_bytes = bytearray()
  async for chunk in edge_tts.Communicate(texto, voz).stream():
      if chunk["type"] == "audio":
          audio_bytes.extend(chunk["data"])


  seg = AudioSegment.from_file(BytesIO(bytes(audio_bytes)), format="mp3").set_channels(1)
  samples = np.array(seg.get_array_of_samples()).astype(np.float32)
  denom = float(1 << (8 * seg.sample_width - 1))
  x = samples / denom
  sr_in = seg.frame_rate


  sr_out = sr_do_device(out_device_index, 'output')
  x = resample_linear(x, sr_in, sr_out).astype(np.float32)


  max_out_ch = sd.query_devices(out_device_index)['max_output_channels']
  out_channels = 2 if max_out_ch >= 2 else 1
  if out_channels == 2:
      x = np.stack([x, x], axis=1)


  with sd.OutputStream(samplerate=sr_out, channels=out_channels,
                       device=out_device_index, dtype='float32') as out_stream:
      block = 4096
      if out_channels == 1:
          for i in range(0, len(x), block):
              out_stream.write(x[i:i+block])
      else:
          for i in range(0, x.shape[0], block):
              out_stream.write(x[i:i+block, :])


def resample_linear(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
  if sr_in == sr_out or len(x) == 0:
      return x
  ratio = sr_out / sr_in
  n_out = int(len(x) * ratio)
  if n_out <= 1:
      return x[:1]
  idx_in = np.linspace(0, len(x) - 1, num=n_out)
  idx0 = np.floor(idx_in).astype(int)
  idx1 = np.minimum(idx0 + 1, len(x) - 1)
  frac = idx_in - idx0
  return (1 - frac) * x[idx0] + frac * x[idx1]


# =========================
#  Pipeline
# =========================
def parar_gravacao(idioma_entrada, idioma_saida, out_device_index):
  global gravacao, stream, ultima_pessoa
  if stream:
      try:
          stream.stop()
          stream.close()
      except Exception:
          pass
  set_status(f"⏳ Processando fala da {ultima_pessoa}…")


  def processar():
      try:
          if not gravacao:
              set_status("⚠️ Nenhum áudio capturado.")
              return


          # Junta os blocos e força mono float32
          audio = np.concatenate(gravacao, axis=0).astype(np.float32)
          if audio.ndim > 1:
              audio = audio.mean(axis=1)
          # faster-whisper espera 16 kHz; resample em memória se necessário
          if samplerate != WHISPER_SR:
              audio = resample_linear(audio, samplerate, WHISPER_SR).astype(np.float32)


          segments, _info = modelo.transcribe(audio, language=idioma_entrada, beam_size=5)
          texto = "".join(seg.text for seg in segments).strip()
          texto_original_label.config(text=texto)


          dest_code = TRANSLATE_CODE_OVERRIDE.get(idioma_saida, idioma_saida)
          traducao = get_translator(dest_code).translate(texto) or ""


          traducao = re.sub(r'\s*\.\s*', '. ', traducao)
          traducao = traducao.replace('.', '')

          texto_traduzido_label.config(text=traducao)


          asyncio.run(falar_texto_edge(traducao, idioma_saida, out_device_index))


          set_status("✅ Pronto para próxima fala")
      except Exception as e:
          set_status(f"❌ Erro: {e}")


  threading.Thread(target=processar, daemon=True).start()


# =========================
#  UI — paleta e tema (Linear/Notion-like)
# =========================
BG          = "#08090A"
BG_ALT      = "#0E0F11"
CARD        = "#101113"
CARD_HOVER  = "#16181C"
CARD_BORDER = "#1F2023"

FG          = "#F7F8F8"
FG_MUTED    = "#8A8F98"
FG_DIM      = "#62666D"

# Acento Pessoa 1: Linear indigo
P1          = "#5E6AD2"
P1_HOVER    = "#6E7AE0"
P1_PRESS    = "#4F58B8"

# Acento Pessoa 2: Linear green
P2          = "#4CB782"
P2_HOVER    = "#5CC792"
P2_PRESS    = "#3FA068"

WARN        = "#E5A848"
DANGER      = "#EB5757"

DOT_OK      = "#4CB782"
DOT_BUSY    = "#E5A848"
DOT_ERR     = "#EB5757"


janela = tk.Tk()
janela.title("Tradutor Bilíngue")
janela.configure(bg=BG)
janela.geometry("1280x820")
janela.minsize(1040, 680)
janela.bind("<F11>", lambda e: janela.attributes('-fullscreen', not janela.attributes('-fullscreen')))
janela.bind("<Escape>", lambda e: janela.attributes('-fullscreen', False))


style = ttk.Style()
style.theme_use("clam")


# Fontes — Helvetica Neue cai bem no macOS
FONT_FAMILY    = "Helvetica Neue"
FONT_TITLE     = (FONT_FAMILY, 26, "bold")
FONT_SUBTITLE  = (FONT_FAMILY, 13)
FONT_SECTION   = (FONT_FAMILY, 11, "bold")
FONT_LABEL     = (FONT_FAMILY, 13)
FONT_TEXT      = (FONT_FAMILY, 13)
FONT_BTN       = (FONT_FAMILY, 13)
FONT_PTT_TITLE = (FONT_FAMILY, 20, "bold")
FONT_PTT_SUB   = (FONT_FAMILY, 12)
FONT_MONO      = ("Menlo", 13)


# Frames
style.configure("TFrame", background=BG)
style.configure("Card.TFrame", background=CARD, borderwidth=0, relief="flat")
style.configure("Inner.TFrame", background=CARD, borderwidth=0, relief="flat")


# Labels
style.configure("TLabel", background=BG, foreground=FG, font=FONT_TEXT)
style.configure("Card.TLabel", background=CARD, foreground=FG, font=FONT_TEXT)
style.configure("Muted.TLabel", background=CARD, foreground=FG_MUTED, font=FONT_LABEL)
style.configure("BgMuted.TLabel", background=BG, foreground=FG_MUTED, font=FONT_LABEL)
style.configure("Title.TLabel", background=BG, foreground=FG, font=FONT_TITLE)
style.configure("Subtitle.TLabel", background=BG, foreground=FG_MUTED, font=FONT_SUBTITLE)
style.configure("Section.TLabel", background=CARD, foreground=FG_DIM, font=FONT_SECTION)
style.configure("Status.TLabel", background=BG, foreground=FG_MUTED, font=FONT_LABEL)
style.configure("Dot.TLabel", background=BG, foreground=DOT_OK, font=(FONT_FAMILY, 16, "bold"))


# Botões discretos (footer / testes)
style.configure("TButton",
               font=FONT_BTN, padding=(14, 9),
               background=CARD_HOVER, foreground=FG_MUTED,
               borderwidth=0, focusthickness=0)
style.map("TButton",
         background=[("active", "#1F2126"), ("pressed", "#0F1013")],
         foreground=[("active", FG), ("disabled", FG_DIM)])


# Combobox
style.configure("TCombobox",
               fieldbackground=CARD, background=CARD, foreground=FG,
               arrowcolor=FG_MUTED, bordercolor=CARD_BORDER,
               lightcolor=CARD_BORDER, darkcolor=CARD_BORDER,
               selectbackground=CARD, selectforeground=FG,
               padding=(12, 10))
style.map("TCombobox",
         fieldbackground=[("readonly", CARD)],
         foreground=[("readonly", FG)],
         bordercolor=[("focus", P1)],
         arrowcolor=[("active", FG)])


janela.option_add("*TCombobox*Listbox.background", CARD)
janela.option_add("*TCombobox*Listbox.foreground", FG)
janela.option_add("*TCombobox*Listbox.selectBackground", P1)
janela.option_add("*TCombobox*Listbox.selectForeground", "white")
janela.option_add("*TCombobox*Listbox.font", FONT_TEXT)
janela.option_add("*TCombobox*Listbox.borderWidth", 0)
janela.option_add("*TCombobox*Listbox.relief", "flat")


# =========================
#  PTTButton — botão grande tipo card, toggle (clique pra começar / clicar pra parar)
# =========================
class PTTButton(tk.Frame):
  _active = None  # apenas um botão pode gravar de cada vez

  def __init__(self, parent, color, color_hover, color_press, person_label):
      super().__init__(parent, bg=color, highlightthickness=0, cursor="hand2")
      self.color_normal = color
      self.color_hover = color_hover
      self.color_press = color_press
      self.person_label = person_label
      self._recording = False
      self._toggle_handler = None

      self.title_lbl = tk.Label(self, text=person_label, bg=color, fg="white", font=FONT_PTT_TITLE)
      self.title_lbl.place(relx=0.5, rely=0.44, anchor="center")

      self.sub_lbl = tk.Label(self, text="Clique para gravar", bg=color, fg="white", font=FONT_PTT_SUB)
      self.sub_lbl.place(relx=0.5, rely=0.6, anchor="center")

      self._children = [self, self.title_lbl, self.sub_lbl]
      for w in self._children:
          w.bind("<Enter>", self._on_enter)
          w.bind("<Leave>", self._on_leave)

  def _set_bg(self, c):
      for w in self._children:
          try:
              w.config(bg=c)
          except Exception:
              pass

  def _on_enter(self, _e):
      if not self._recording:
          self._set_bg(self.color_hover)

  def _on_leave(self, _e):
      if not self._recording:
          self._set_bg(self.color_normal)

  def _set_recording_visual(self):
      self._set_bg(self.color_press)
      self.title_lbl.config(text="● Gravando")
      self.sub_lbl.config(text="Clique para parar")

  def _set_idle_visual(self):
      self._set_bg(self.color_normal)
      self.title_lbl.config(text=self.person_label)
      self.sub_lbl.config(text="Clique para gravar")

  def bind_toggle(self, on_start, on_stop):
      def _click(e=None):
          if self._recording:
              self._recording = False
              PTTButton._active = None
              self._set_idle_visual()
              on_stop(e)
          else:
              if PTTButton._active is not None:
                  set_status("⚠️ Outra pessoa está gravando — pare antes de iniciar.")
                  return
              self._recording = True
              PTTButton._active = self
              self._set_recording_visual()
              on_start(e)
      self._toggle_handler = _click
      for w in self._children:
          w.bind("<ButtonPress-1>", _click)


# =========================
#  Header
# =========================
header = ttk.Frame(janela, style="TFrame")
header.pack(fill="x", padx=32, pady=(28, 18))


header_left = ttk.Frame(header, style="TFrame")
header_left.pack(side="left")

title_lbl = ttk.Label(header_left, text="Tradutor Simultâneo", style="Title.TLabel")
title_lbl.pack(anchor="w")

subtitle_lbl = ttk.Label(header_left,
                       text="Conversação bilíngue em tempo real",
                       style="Subtitle.TLabel")
subtitle_lbl.pack(anchor="w", pady=(4, 0))


# Status à direita do header
header_right = ttk.Frame(header, style="TFrame")
header_right.pack(side="right")

status_dot = ttk.Label(header_right, text="●", style="Dot.TLabel")
status_dot.pack(side="left", padx=(0, 8))

status_label = ttk.Label(header_right, text="Pronto", style="Status.TLabel")
status_label.pack(side="left")


def set_status(msg: str):
  status_label.config(text=msg)
  color = DOT_OK
  if "❌" in msg or "Erro" in msg:
      color = DOT_ERR
  elif ("⚠️" in msg or "⏳" in msg or "Gravando" in msg
        or "Tocando" in msg or "Processando" in msg or "Beep" in msg):
      color = DOT_BUSY
  try:
      status_dot.config(foreground=color)
  except Exception:
      pass


# (opcional) ícone
try:
  mic_img = Image.open("microfone.png").resize((22, 22))
  mic_icon = ImageTk.PhotoImage(mic_img)
except Exception:
  mic_icon = None


# =========================
#  Main grid
# =========================
main = ttk.Frame(janela, style="TFrame")
main.pack(fill="both", expand=True, padx=32, pady=(0, 12))
main.grid_columnconfigure(0, weight=1, uniform="col")
main.grid_columnconfigure(1, weight=1, uniform="col")
main.grid_rowconfigure(0, weight=0)   # settings — altura natural
main.grid_rowconfigure(1, weight=3)   # PTT — protagonista, mas equilibrado
main.grid_rowconfigure(2, weight=2)   # resultados


# ---- Card: Idiomas ----
card_lang = ttk.Frame(main, style="Card.TFrame")
card_lang.grid(row=0, column=0, sticky="nsew", padx=(0, 12), pady=(0, 12))
ttk.Label(card_lang, text="IDIOMAS", style="Section.TLabel").pack(anchor="w", padx=26, pady=(22, 16))


idioma_origem = tk.StringVar(value="🇧🇷 Português (Brasil)")
idioma_destino = tk.StringVar(value="🇺🇸 Inglês")


frm_lang = ttk.Frame(card_lang, style="Card.TFrame")
frm_lang.pack(fill="x", padx=26, pady=(0, 24))
frm_lang.grid_columnconfigure(1, weight=1)


ttk.Label(frm_lang, text="Pessoa 1", style="Muted.TLabel").grid(row=0, column=0, sticky="w", pady=(2,8), padx=(0,14))
cb_p1 = ttk.Combobox(frm_lang, values=list(idiomas.keys()), textvariable=idioma_origem, state="readonly", height=14)
cb_p1.grid(row=0, column=1, sticky="ew", pady=(2,8))


ttk.Label(frm_lang, text="Pessoa 2", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(8,2), padx=(0,14))
cb_p2 = ttk.Combobox(frm_lang, values=list(idiomas.keys()), textvariable=idioma_destino, state="readonly", height=14)
cb_p2.grid(row=1, column=1, sticky="ew", pady=(8,2))


# ---- Card: Dispositivos (1 device por pessoa, mic+saída) ----
dispositivos = listar_dispositivos_unico()
dev_labels = [d[0] for d in dispositivos]


def _default_duplex():
  for label, idx in dispositivos:
      try:
          if sd.query_devices(idx).get('max_output_channels', 0) > 0:
              return label
      except Exception:
          pass
  return dev_labels[0] if dev_labels else ""


_default_dev = _default_duplex()
dev1_var = tk.StringVar(value=_default_dev)
dev2_var = tk.StringVar(value=_default_dev)


card_dev = ttk.Frame(main, style="Card.TFrame")
card_dev.grid(row=0, column=1, sticky="nsew", padx=(12, 0), pady=(0, 12))
ttk.Label(card_dev, text="DISPOSITIVOS", style="Section.TLabel").pack(anchor="w", padx=26, pady=(22, 16))


frm_dev = ttk.Frame(card_dev, style="Card.TFrame")
frm_dev.pack(fill="x", padx=26, pady=(0, 24))
frm_dev.grid_columnconfigure(1, weight=1)


ttk.Label(frm_dev, text="Pessoa 1", style="Muted.TLabel").grid(row=0, column=0, sticky="w", pady=(2,8), padx=(0,14))
cb_dev1 = ttk.Combobox(frm_dev, values=dev_labels, textvariable=dev1_var, state="readonly", height=14)
cb_dev1.grid(row=0, column=1, sticky="ew", pady=(2,8))


ttk.Label(frm_dev, text="Pessoa 2", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(8,2), padx=(0,14))
cb_dev2 = ttk.Combobox(frm_dev, values=dev_labels, textvariable=dev2_var, state="readonly", height=14)
cb_dev2.grid(row=1, column=1, sticky="ew", pady=(8,2))


# ---- Row 1: BIG Push-to-talk buttons ----
ptt_row = ttk.Frame(main, style="TFrame")
ptt_row.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(4, 12))
ptt_row.grid_columnconfigure(0, weight=1, uniform="ptt")
ptt_row.grid_columnconfigure(1, weight=1, uniform="ptt")
ptt_row.grid_rowconfigure(0, weight=1)


btn_p1 = PTTButton(ptt_row, P1, P1_HOVER, P1_PRESS, "Pessoa 1")
btn_p1.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

btn_p2 = PTTButton(ptt_row, P2, P2_HOVER, P2_PRESS, "Pessoa 2")
btn_p2.grid(row=0, column=1, sticky="nsew", padx=(12, 0))


# ---- Row 2: Resultados (lado a lado) ----
card_out = ttk.Frame(main, style="Card.TFrame")
card_out.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(0, 0))
ttk.Label(card_out, text="TRANSCRIÇÃO E TRADUÇÃO", style="Section.TLabel").pack(anchor="w", padx=26, pady=(22, 16))


text_frame = ttk.Frame(card_out, style="Card.TFrame")
text_frame.pack(fill="both", expand=True, padx=26, pady=(0, 24))
text_frame.grid_columnconfigure(0, weight=1, uniform="txt")
text_frame.grid_columnconfigure(1, weight=1, uniform="txt")
text_frame.grid_rowconfigure(1, weight=1)


def make_text(parent, accent):
  t = tk.Text(parent, height=5, bg=BG_ALT, fg=FG, insertbackground=FG,
              relief="flat", wrap="word", font=FONT_MONO, padx=16, pady=14,
              selectbackground=accent, selectforeground="white",
              highlightthickness=1, highlightbackground=CARD_BORDER, highlightcolor=accent)
  t.bind("<Key>", lambda e: "break")
  return t


ttk.Label(text_frame, text="ORIGINAL", style="Section.TLabel").grid(row=0, column=0, sticky="w", padx=(0,8), pady=(0,8))
ttk.Label(text_frame, text="TRADUÇÃO", style="Section.TLabel").grid(row=0, column=1, sticky="w", padx=(8,0), pady=(0,8))

txt_original = make_text(text_frame, P1)
txt_original.grid(row=1, column=0, sticky="nsew", padx=(0,8))

txt_traducao = make_text(text_frame, P2)
txt_traducao.grid(row=1, column=1, sticky="nsew", padx=(8,0))


def update_text(widget, content):
  widget.configure(state="normal")
  widget.delete("1.0", "end")
  widget.insert("1.0", content)
  widget.configure(state="disabled")


def set_texto_original(txt):
  update_text(txt_original, txt)


def set_texto_traduzido(txt):
  update_text(txt_traducao, txt)


texto_original_label = type("shim", (), {"config": lambda self, text: set_texto_original(text)})()
texto_traduzido_label = type("shim", (), {"config": lambda self, text: set_texto_traduzido(text)})()


# ---- Footer: atalhos + testes ----
footer = ttk.Frame(janela, style="TFrame")
footer.pack(fill="x", padx=32, pady=(10, 22))


hint = ttk.Label(footer,
               text="Clique para iniciar / parar a gravação   ·   Ctrl+1 (P1)   ·   Ctrl+2 (P2)   ·   F11 tela cheia",
               style="BgMuted.TLabel")
hint.pack(side="left")


def teste_beep_var(var):
  try:
      idx = output_device_for(label_para_index(var.get()))
      if idx is None:
          set_status("❌ Selecione uma saída válida.")
          return
      sr = sr_do_device(idx, 'output')
      ch = 2 if sd.query_devices(idx)['max_output_channels'] >= 2 else 1
      dur = 0.25
      t = np.linspace(0, dur, int(sr*dur), endpoint=False)
      tone = 0.2*np.sin(2*np.pi*660*t).astype(np.float32)
      x = np.stack([tone, tone], axis=1) if ch == 2 else tone
      set_status(f"🔔 Beep no device {idx}")
      sd.play(x, sr, device=idx, blocking=True)
  except Exception as e:
      set_status(f"❌ Erro no beep: {e}")


ttk.Button(footer, text="Testar P2", command=lambda: teste_beep_var(dev2_var)).pack(side="right", padx=(8,0))
ttk.Button(footer, text="Testar P1", command=lambda: teste_beep_var(dev1_var)).pack(side="right")


# =========================
#  Handlers (P1 fala → P2 ouve a tradução, e vice-versa)
# =========================
def on_press_p1(_e=None):
  mic_idx = label_para_index(dev1_var.get())
  set_status("🎤 Gravando Pessoa 1…")
  iniciar_gravacao("Pessoa 1", mic_idx)


def on_release_p1(_e=None):
  out_idx = output_device_for(label_para_index(dev2_var.get()))
  parar_gravacao(
      idiomas[idioma_origem.get()],
      idiomas[idioma_destino.get()],
      out_idx
  )


def on_press_p2(_e=None):
  mic_idx = label_para_index(dev2_var.get())
  set_status("🎤 Gravando Pessoa 2…")
  iniciar_gravacao("Pessoa 2", mic_idx)


def on_release_p2(_e=None):
  out_idx = output_device_for(label_para_index(dev1_var.get()))
  parar_gravacao(
      idiomas[idioma_destino.get()],
      idiomas[idioma_origem.get()],
      out_idx
  )


btn_p1.bind_toggle(on_press_p1, on_release_p1)
btn_p2.bind_toggle(on_press_p2, on_release_p2)


# Atalhos: Ctrl+1 / Ctrl+2 (toggle igual ao clique)
janela.bind("<Control-Key-1>", lambda e: btn_p1._toggle_handler(e))
janela.bind("<Control-Key-2>", lambda e: btn_p2._toggle_handler(e))


# =========================

# ================
if __name__ == "__main__":
  janela.mainloop()
