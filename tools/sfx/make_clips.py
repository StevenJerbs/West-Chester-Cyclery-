"""Cut the chosen moments out of the Vital RAW recording, bake seamless loops, normalise, encode as small mono MP3s
and write them as a JS object of data URIs for the page."""
import subprocess, numpy as np, base64, json, os, sys
SRC = 'src.m4a'; SR = 22050
raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', SRC, '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'], capture_output=True).stdout
x = np.frombuffer(raw, np.float32)
# name: (start s, duration s, loop?, peak dBFS, highpass Hz)
CLIPS = {
    'roll':   (22.6,  1.3, True,  -3, 80),    # tyre roll, mid pass-by, broadband
    'rough':  (7.15,  1.0, True,  -3, 60),    # rough section: roll with chatter
    'buzz':   (250.0, 0.5, True,  -6, 1500),  # freehub at speed (~650 Hz click train)
    'buzz2':  (390.0, 0.5, True,  -6, 1500),
    'hit1':   (7.95,  0.7, False, -1, 40),    # landing thud
    'hit2':   (7.25,  0.6, False, -1, 40),
    'hit3':   (641.15, 0.6, False, -2, 40),
    'hit4':   (787.35, 0.7, False, -2, 40),
    'whoosh': (878.5, 1.6, False, -4, 60),    # a pass with the Doppler fall: the takeoff
    'wind':   (412.0, 1.6, True,  -8, 120),   # wind in the trees
    'amb':    (318.0, 4.0, True,  -14, 60),   # forest bed
}
def highpass(s, fc):
    X = np.fft.rfft(s); f = np.fft.rfftfreq(len(s), 1 / SR); X *= 1 / (1 + (fc / np.maximum(f, 1e-3)) ** 4); return np.fft.irfft(X, len(s)).astype(np.float32)
out = {}; total = 0
for name, (t0, d, loop, peak, hp) in CLIPS.items():
    s = x[int(t0 * SR):int((t0 + d) * SR)].astype(np.float64); s -= s.mean(); s = highpass(s, hp)
    n = len(s); fade = int(SR * 0.006)
    if loop:  # equal-power crossfade of the last 120 ms into the first 120 ms, then drop the tail
        cf = int(SR * 0.12); a = s[:cf]; b = s[-cf:]; w = np.linspace(0, 1, cf)
        s[:cf] = a * np.sqrt(1 - w) + b * np.sqrt(w); s = s[:n - cf]
    else:     # short fades so the one-shots do not click
        s[:fade] *= np.linspace(0, 1, fade); s[-fade * 4:] *= np.linspace(1, 0, fade * 4)
    s *= 10 ** (peak / 20) / (np.abs(s).max() + 1e-9)
    wav = name + '.wav'; mp3 = name + '.mp3'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'f32le', '-ar', str(SR), '-ac', '1', '-i', '-', wav], input=s.astype(np.float32).tobytes(), check=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', wav, '-c:a', 'libmp3lame', '-b:a', '48k', '-ar', str(SR), '-ac', '1', mp3], check=True)
    b = open(mp3, 'rb').read(); total += len(b)
    out[name] = 'data:audio/mpeg;base64,' + base64.b64encode(b).decode()
    print('%-7s %5.2f s  %6d B' % (name, len(s) / SR, len(b)))
open('sfx_data.js', 'w').write('const SFX_DATA = ' + json.dumps(out) + ';\n')
print('total mp3 bytes', total, ' js bytes', os.path.getsize('sfx_data.js'))
