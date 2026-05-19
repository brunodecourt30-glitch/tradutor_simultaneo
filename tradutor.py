import tkinter as tk
import threading
import sounddevice as sd
import numpy as np
import soundfile as sf
import whisper
import edge_tts
import asyncio
import os
from googletrans import Translator
from pydub import AudioSegment
import tempfile

# -----------------------
# Idiomas e Whisper
# -----------------------
idiomas = {
    "🇧🇷 Português": "pt",
    "🇺🇸 Inglês": "en",
    "🇪🇸 Espanhol": "es",
    "🇫🇷 Francês": "fr",
    "🇸🇦 Árabe": "ar",
    "🇭🇹 Haitiano": "ht",
    "🇳🇱 Holandês": "nl"
}

modelo = whisper.load_model("medium")

gravacao = []
samplerate = 16000
stream = None
ultima_pessoa = None

# -----------------------
# Utils: buscar devices por nome
# -----------------------
def find_output_by_keywords(keywords):
    devices = sd.query_devices()
    for idx, d in enumerate(devices):
        if d["max_output_channels"] <= 0:
            continue
        name = (d["name"] or "").lower()
        if all(k.lower() in name for k in keywords):
            return idx
    return None

def find_input_by_keywords(keywords):
    devices = sd.query_devices()
    for idx, d in enumerate(devices):
        if d["max_input_channels"] <= 0:
            continue
        name = (d["name"] or "").lower()
        if all(k.lower() in name for k in keywords):
            return idx
    return None

def tocar_mp3_no_device(mp3_path, device_index):
    audio = AudioSegment.from_file(mp3_path, format="mp3")
    samples = np.array(audio.get_array_of_samples())
    max_int = float(2 ** (8 * audio.sample_width - 1))
    samples = samples.astype(np.float32) / max_int
    if audio.channels > 1:
        samples = samples.reshape((-1, audio.channels))
    sd.play(samples, samplerate=audio.frame_rate, device=device_index)
    sd.wait()

# -----------------------
# Descobrir SAÍDAS fixas (P1→AirPods | P2→Fio)
# -----------------------
idx_airpods_out = (find_output_by_keywords(["airpods"])
                   or find_output_by_keywords(["bluetooth", "airpods"]))
idx_wired_out = (find_output_by_keywords(["fones", "externos"])
                 or find_output_by_keywords(["headphone"])
                 or find_output_by_keywords(["built-in", "output"])
                 or find_output_by_keywords(["usb", "audio"]))

# -----------------------
# Descobrir MICROFONES (ENTRADA)
# P1 = AirPods (ou MacBook se não achar)
# P2 = Microfone Externo (fio) se existir
# -----------------------
idx_airpods_mic = (find_input_by_keywords(["airpods"])
                   or find_input_by_keywords(["bluetooth"]))
idx_mac_mic = find_input_by_keywords(["macbook", "integrado"]) or find_input_by_keywords(["built-in"])
idx_wired_mic = (find_input_by_keywords(["microfone", "externo"])
                 or find_input_by_keywords(["external", "microphone"])
                 or find_input_by_keywords(["usb", "audio"]))

# Regra: P1 usa AirPods se houver; senão usa mic do Mac
idx_mic_p1 = idx_airpods_mic if idx_airpods_mic is not None else idx_mac_mic
# Regra: P2 usa microfone externo (fio); se não houver, fica no default (None)
idx_mic_p2 = idx_wired_mic

# -----------------------
# Tk UI
# -----------------------
janela = tk.Tk()
janela.title("Tradutor Bilíngue (Opção 1: mics separados por pessoa)")
janela.geometry("680x720")
janela.configure(bg="white")

idioma_origem = tk.StringVar(value="🇧🇷 Português")
idioma_destino = tk.StringVar(value="🇺🇸 Inglês")

# Informativo dos devices detectados
def label_val(v):
    return "ok" if v is not None else "não encontrado"

info_text = (
    f"Saídas:\n"
    f"  Pessoa 1 → AirPods idx={idx_airpods_out} ({label_val(idx_airpods_out)})\n"
    f"  Pessoa 2 → Fone com fio idx={idx_wired_out} ({label_val(idx_wired_out)})\n\n"
    f"Microfones:\n"
    f"  P1 → AirPods idx={idx_mic_p1} ({'AirPods' if idx_mic_p1==idx_airpods_mic else 'MacBook'})\n"
    f"  P2 → Fio idx={idx_mic_p2} ({label_val(idx_mic_p2)})\n"
)
tk.Label(janela, text=info_text, bg="white", font=("Helvetica", 12)).pack(pady=6)

# -----------------------
# Gravação / TTS
# -----------------------
def callback(indata, frames, time, status):
    global gravacao
    gravacao.append(indata.copy())

def iniciar_gravacao(pessoa):
    global gravacao, stream, ultima_pessoa
    gravacao = []
    ultima_pessoa = pessoa
    status_label.config(text=f"🎤 Gravando {pessoa}...")

    # escolhe o mic de acordo com a pessoa
    mic_idx = idx_mic_p1 if pessoa == "Pessoa 1" else idx_mic_p2
    if mic_idx is None:
        status_label.config(text=f"⚠️ Microfone da {pessoa} não encontrado.")
        return

    stream = sd.InputStream(
        samplerate=samplerate,
        channels=1,
        callback=callback,
        device=mic_idx
    )
    stream.start()

async def _tts_to_file(texto, idioma):
    if idioma == "pt":   voice = "pt-BR-AntonioNeural"
    elif idioma == "en": voice = "en-US-GuyNeural"
    elif idioma == "es": voice = "es-ES-AlvaroNeural"
    elif idioma == "fr": voice = "fr-FR-DeniseNeural"
    elif idioma == "ar": voice = "ar-EG-SalmaNeural"
    elif idioma == "ht": voice = "en-US-GuyNeural"
    elif idioma == "nl": voice = "nl-NL-MaartenNeural"
    else:                voice = "en-US-GuyNeural"

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    tmp_path = tmp.name
    tmp.close()
    await edge_tts.Communicate(texto, voice=voice).save(tmp_path)
    return tmp_path

def falar_texto_edge_para_device(texto, idioma, device_index):
    async def speak_and_play():
        mp3_path = await _tts_to_file(texto, idioma)
        try:
            tocar_mp3_no_device(mp3_path, device_index)
        finally:
            try: os.remove(mp3_path)
            except: pass
    asyncio.run(speak_and_play())

def parar_gravacao(idioma_entrada, idioma_saida):
    global gravacao, stream, ultima_pessoa
    if stream:
        stream.stop()
        stream.close()
    status_label.config(text=f"⏳ Processando fala da {ultima_pessoa}...")

    def processar():
        if not gravacao:
            status_label.config(text="⚠️ Nenhum áudio capturado.")
            return

        audio = np.concatenate(gravacao, axis=0)
        sf.write("entrada.wav", audio, samplerate)

        # transcrição
        resultado = modelo.transcribe("entrada.wav", language=idioma_entrada)
        texto = resultado['text']
        texto_original_label.config(text=f"{ultima_pessoa} disse: {texto}")

        # tradução
        traducao = Translator().translate(texto, dest=idioma_saida).text
        texto_traduzido_label.config(text=f"Tradução: {traducao}")

        # saída fixa por pessoa
        if ultima_pessoa == "Pessoa 1":
            out_idx = idx_airpods_out
            if out_idx is None:
                status_label.config(text="❌ Saída AirPods (P1) não encontrada.")
                return
        else:
            out_idx = idx_wired_out
            if out_idx is None:
                status_label.config(text="❌ Saída fone com fio (P2) não encontrada.")
                return

        falar_texto_edge_para_device(traducao, idioma_saida, out_idx)

        try: os.remove("entrada.wav")
        except: pass
        status_label.config(text="✅ Pronto para próxima fala")

    threading.Thread(target=processar, daemon=True).start()

# -----------------------
# UI mínima (só idiomas e botões)
# -----------------------
menu1_label = tk.Label(janela, text="Idioma da Pessoa 1 (fala)", bg="white", font=("Helvetica", 13))
menu1 = tk.OptionMenu(janela, idioma_origem, *idiomas.keys())
menu2_label = tk.Label(janela, text="Idioma da Pessoa 2 (fala)", bg="white", font=("Helvetica", 13))
menu2 = tk.OptionMenu(janela, idioma_destino, *idiomas.keys())
for w in (menu1, menu2):
    w.config(width=30, font=("Helvetica", 12))

def formatar_botao(b):
    b.config(height=3, width=30, font=("Helvetica", 15), bg="#2563EB", fg="white", activebackground="#1D4ED8")

botao1 = tk.Button(janela, text="🎙️ Pessoa 1 Fala")
botao1.bind("<ButtonPress-1>", lambda e: iniciar_gravacao("Pessoa 1"))
botao1.bind("<ButtonRelease-1>", lambda e: parar_gravacao(idiomas[idioma_origem.get()], idiomas[idioma_destino.get()]))
formatar_botao(botao1)

botao2 = tk.Button(janela, text="🎙️ Pessoa 2 Fala")
botao2.bind("<ButtonPress-1>", lambda e: iniciar_gravacao("Pessoa 2"))
botao2.bind("<ButtonRelease-1>", lambda e: parar_gravacao(idiomas[idioma_destino.get()], idiomas[idioma_origem.get()]))
formatar_botao(botao2)

status_label = tk.Label(janela, text="Aguardando...", fg="#0F766E", bg="white", font=("Helvetica", 14))
texto_original_label = tk.Label(janela, text="", wraplength=600, bg="white", font=("Helvetica", 12))
texto_traduzido_label = tk.Label(janela, text="", wraplength=600, fg="#065F46", bg="white", font=("Helvetica", 12))

menu1_label.pack(pady=(8,2)); menu1.pack(pady=2)
menu2_label.pack(pady=(8,2)); menu2.pack(pady=2)
botao1.pack(pady=16)
botao2.pack(pady=8)
status_label.pack(pady=10)
texto_original_label.pack(pady=6)
texto_traduzido_label.pack(pady=6)

janela.mainloop()

