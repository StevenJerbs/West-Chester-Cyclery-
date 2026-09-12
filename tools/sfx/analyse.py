"""Find usable sound moments in a trackside DH recording: bike pass-bys (sustained broadband), freehub buzz
(high-band, periodic), impacts (fast onsets with low-band weight) and quiet stretches (ambience)."""
import subprocess, numpy as np, sys, json
SRC = sys.argv[1]; SR = 22050
raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', SRC, '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'], capture_output=True).stdout
x = np.frombuffer(raw, np.float32); N = len(x); T = N / SR
FR = int(SR * 0.05); nF = N // FR
win = np.hanning(FR * 2)
feat = []
freqs = np.fft.rfftfreq(FR * 2, 1 / SR)
lo = (freqs >= 40) & (freqs < 250); mid = (freqs >= 250) & (freqs < 2500); hi = (freqs >= 2500) & (freqs < 9000)
for i in range(1, nF - 1):
    seg = x[(i - 1) * FR:(i + 1) * FR] * win
    rms = float(np.sqrt(np.mean(seg * seg)) + 1e-9)
    S = np.abs(np.fft.rfft(seg)) ** 2 + 1e-12
    tot = S.sum(); cen = float((freqs * S).sum() / tot)
    feat.append((i * FR / SR, rms, float(S[lo].sum() / tot), float(S[mid].sum() / tot), float(S[hi].sum() / tot), cen))
F = np.array(feat); t = F[:, 0]; rms = F[:, 1]; lo_r = F[:, 2]; hi_r = F[:, 4]; cen = F[:, 5]
db = 20 * np.log10(rms)
bg = np.percentile(db, 20)
print('duration %.1f s  background %.1f dBFS  median %.1f  p95 %.1f  max %.1f' % (T, bg, np.median(db), np.percentile(db, 95), db.max()))
# smooth
k = 10; sm = np.convolve(db, np.ones(k) / k, 'same')
# pass-bys: contiguous stretches > bg+12 dB lasting 0.6-6 s
thr = bg + 12; on = sm > thr; ev = []; i = 0
while i < len(on):
    if on[i]:
        j = i
        while j < len(on) and on[j]: j += 1
        d = (j - i) * 0.05
        if 0.6 <= d <= 8: ev.append((t[i], d, float(sm[i:j].max()), float(np.mean(hi_r[i:j])), float(np.mean(lo_r[i:j])), float(np.mean(cen[i:j]))))
        i = j
    else: i += 1
ev.sort(key=lambda e: -e[2])
print('\nPASS-BYS (start, dur, peak dB, hi ratio, lo ratio, centroid) top 25:')
for e in ev[:25]: print('  %7.1f  %4.1f s  %6.1f dB  hi %.2f  lo %.2f  cen %5.0f Hz' % e)
# impacts: onset = db jump > 10 dB within 100 ms with lo ratio > 0.25
d1 = np.diff(db, 2)
imp = []
for i in range(3, len(db) - 3):
    jump = db[i] - db[i - 2]
    if jump > 10 and db[i] > bg + 15 and lo_r[i] > 0.2 and (not imp or t[i] - imp[-1][0] > 0.4):
        imp.append((t[i], float(jump), float(db[i]), float(lo_r[i])))
imp.sort(key=lambda e: -e[2])
print('\nIMPACTS (t, jump dB, level dB, lo ratio) top 25:')
for e in imp[:25]: print('  %7.1f  +%4.1f  %6.1f  lo %.2f' % e)
# buzz: hi ratio > 0.45 with modest level, sustained >= 0.5 s
on = (hi_r > 0.45) & (db > bg + 6) & (db < bg + 30); bz = []; i = 0
while i < len(on):
    if on[i]:
        j = i
        while j < len(on) and on[j]: j += 1
        d = (j - i) * 0.05
        if d >= 0.5: bz.append((t[i], d, float(db[i:j].mean()), float(hi_r[i:j].mean())))
        i = j
    else: i += 1
bz.sort(key=lambda e: -e[1])
print('\nHIGH-BAND SUSTAINED (freehub candidates) top 15:')
for e in bz[:15]: print('  %7.1f  %4.1f s  %6.1f dB  hi %.2f' % e)
# quiet stretches for ambience: 4 s windows with lowest max level
q = []
w = 80
for i in range(0, len(db) - w, 20): q.append((t[i], float(sm[i:i + w].max()), float(np.mean(cen[i:i + w]))))
q.sort(key=lambda e: e[1])
print('\nQUIET 4 s windows (t, max dB, centroid):')
for e in q[:8]: print('  %7.1f  %6.1f dB  cen %5.0f' % e)
