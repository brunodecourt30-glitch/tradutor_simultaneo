import sounddevice as sd
import soundfile as sf

print("Gravando por 3 segundos...")
gravação = sd.rec(int(3 * 16000), samplerate=16000, channels=1)
sd.wait()

sf.write("teste_microfone.wav", gravação, 16000)
print("Gravação salva em teste_microfone.wav")
