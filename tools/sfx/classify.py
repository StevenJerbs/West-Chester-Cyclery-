"""Second pass: for candidate windows, measure click periodicity (freehub), harmonicity (voice/motor), spectral
flatness (tyre/wind noise) and the Doppler drift of the centroid (a real pass-by falls in pitch)."""
import subprocess, numpy as np, sys
SRC = sys.argv[1]; SR = 22050
raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', SRC, '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'], capture_output=True).stdout
x = np.frombuffer(raw, np.float32)
def acorr(v):
    v = v[:SR]; n = len(v); F = np.fft.rfft(v, 2 * n); a = np.fft.irfft(F * np.conj(F))[:n]; return a / (a[0] + 1e-9)
def band(sig, lo, hi):
    X = np.fft.rfft(sig); f = np.fft.rfftfreq(len(sig), 1 / SR); X[(f < lo) | (f > hi)] = 0; return np.fft.irfft(X, len(sig))
def feats(t0, d):
    s = x[int(t0 * SR):int((t0 + d) * SR)]
    if len(s) < SR // 4: return None
    s = s - s.mean()
    # click periodicity: envelope of the 2.5-9 kHz band, autocorrelation peak between 2.5 and 14 ms
    h = np.abs(band(s, 2500, 9000)); env = np.convolve(h, np.ones(int(SR * 0.0005)) / int(SR * 0.0005), 'same'); env -= env.mean()
    ac = acorr(env)
    l0, l1 = int(SR * 0.0015), int(SR * 0.014); seg = ac[l0:l1]
    pk = [i for i in range(1, len(seg) - 1) if seg[i] > seg[i - 1] and seg[i] >= seg[i + 1]]
    k = (l0 + max(pk, key=lambda i: seg[i])) if pk else 0; clickP = float(ac[k]) if k else 0.0; clickHz = SR / k if k else 0
    # harmonicity: autocorrelation of the 80-1500 Hz band at 2-12 ms lags (voices, motors)
    m = band(s, 80, 1500); ac2 = acorr(m)
    l0, l1 = int(SR * 0.002), int(SR * 0.012); seg2 = ac2[l0:l1]
    pk2 = [i for i in range(1, len(seg2) - 1) if seg2[i] > seg2[i - 1] and seg2[i] >= seg2[i + 1]]
    k2 = (l0 + max(pk2, key=lambda i: seg2[i])) if pk2 else 0; harm = float(ac2[k2]) if k2 else 0.0; harmHz = SR / k2 if k2 else 0
    # spectral flatness of the whole window
    S = np.abs(np.fft.rfft(s * np.hanning(len(s)))) ** 2 + 1e-12; flat = float(np.exp(np.mean(np.log(S))) / np.mean(S))
    # centroid drift first third -> last third (Doppler)
    f = np.fft.rfftfreq(len(s), 1 / SR)
    def cen(seg):
        P = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2 + 1e-12; ff = np.fft.rfftfreq(len(seg), 1 / SR); return float((ff * P).sum() / P.sum())
    n = len(s) // 3; drift = cen(s[-n:]) - cen(s[:n])
    rms = 20 * np.log10(np.sqrt(np.mean(s * s)) + 1e-9)
    return clickP, clickHz, harm, harmHz, flat, drift, rms
cands = [('passby', 656.6, 1.9), ('passby', 878.3, 3.1), ('passby', 7.0, 1.8), ('passby', 14.7, 0.8), ('passby', 336.8, 1.2), ('passby', 388.5, 0.8),
         ('passby', 22.3, 1.9), ('passby', 209.7, 1.5), ('passby', 19.7, 0.8), ('passby', 779.8, 4.8), ('passby', 827.8, 2.2), ('passby', 245.2, 0.8),
         ('passby', 867.6, 3.5), ('passby', 753.7, 4.4), ('passby', 581.8, 1.6), ('passby', 405.2, 0.9), ('passby', 606.9, 1.0), ('passby', 43.1, 1.1),
         ('buzz', 656.9, 0.9), ('buzz', 668.8, 0.8), ('buzz', 720.5, 0.8), ('buzz', 651.9, 0.7), ('buzz', 14.8, 0.7), ('buzz', 19.8, 0.6), ('buzz', 337.4, 0.6),
         ('buzz', 490.2, 0.6), ('buzz', 250.0, 0.5), ('buzz', 390.0, 0.5),
         ('impact', 8.1, 0.5), ('impact', 7.4, 0.5), ('impact', 641.2, 0.5), ('impact', 787.4, 0.5), ('impact', 760.5, 0.5), ('impact', 162.5, 0.5), ('impact', 281.9, 0.5), ('impact', 6.0, 0.5),
         ('quiet', 137.0, 4.0), ('quiet', 411.9, 4.0), ('quiet', 279.9, 4.0), ('quiet', 166.0, 4.0), ('quiet', 317.9, 4.0)]
print('%-7s %7s %5s | click  %5s | harm  %5s | flat  | drift  | dB' % ('kind', 't', 'dur', 'Hz', 'Hz'))
for kind, t0, d in cands:
    r = feats(t0, d)
    if r: print('%-7s %7.1f %5.1f | %.2f %6.0f | %.2f %6.0f | %.3f | %+6.0f | %5.1f' % ((kind, t0, d) + r))
