import json
import re
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

MODEL = "kokoro-v1.0.onnx"
VOICES = "voices-v1.0.bin"
VOICE = "am_michael"
LANG = "en-us"
OUT = Path("kokoro-output")
OUT.mkdir(exist_ok=True)

SCENES = [
    ("hook", 21.360542, "Most trading strategies are noise wearing a beautiful equity curve. If you try enough indicators, markets, and settings, something will look amazing by accident. The goal is not to find a chart that went up. The goal is to build a simple hypothesis, test it fairly, and see whether the edge survives every reasonable attempt to kill it."),
    ("meaning", 29.450021, "Statistical significance does not mean guaranteed profit. It means the result would be unusual if your strategy had no real edge. Start with a null hypothesis: after realistic costs, the strategy's expected excess return is zero or worse. Then estimate how often random chance could produce a result at least this strong. That probability is the p value. A low p value is evidence, not certainty, and it says nothing about whether the edge is large enough to matter."),
    ("hypothesis", 25.872563, "A valid strategy begins as a falsifiable sentence. For example: after a large overnight gap, liquid stocks tend to partially reverse during the first hour. Define the market, signal, entry time, exit time, position sizing, maximum risk, and every exclusion rule. Keep the first version simple. If you invent rules after seeing the result, you are fitting the story to the answer."),
    ("split", 27.037688, "Financial data is ordered through time, so do not randomly shuffle it like ordinary machine learning data. Use an early research period to design the idea, a later validation period for a small number of decisions, and a final lockbox period that remains untouched until the strategy is frozen. Better still, use walk-forward tests: train on the past, test on the next window, then roll forward. The future must never leak backward."),
    ("realism", 23.068479, "A backtest should include commissions, bid ask spread, slippage, delayed fills, borrow fees for shorts, liquidity limits, and delisted assets. Use only information that truly existed at the decision time. Stress every cost upward. If a tiny increase in slippage destroys the strategy, you do not have a durable edge; you have a spreadsheet artifact."),
    ("test", 32.742458, "Do not judge only the final account balance. Measure net return per trade, volatility, drawdown, turnover, exposure, and performance by market regime. Then estimate uncertainty. A practical method is a block bootstrap: resample chunks of consecutive returns so clustering and autocorrelation are partly preserved. Build thousands of simulated histories and calculate a confidence interval for the average net edge. A strong result has a lower confidence bound above zero, not merely a positive average."),
    ("multiple", 28.693708, "This is where most strategy research fails. If twenty useless strategies are tested at a five percent significance level, you expect about one false positive, and there is roughly a sixty four percent chance that at least one appears significant. Record every trial, including failures. Use a stricter threshold such as Bonferroni, or control the false discovery rate with Benjamini Hochberg. Never report the winner without reporting the size of the search."),
    ("robustness", 26.823313, "Now attack the strategy. Shift entries by a few minutes. Raise costs. Change markets. Remove the best month. Test calm, volatile, rising, and falling regimes. Vary parameters across a broad neighborhood. Real effects usually form a stable plateau. Overfit effects often live on a single sharp peak. Also compare against simple baselines, because complexity must earn its place."),
    ("paper", 26.253104, "Once the lockbox test is complete, freeze the code and paper trade forward. Define failure rules before the experiment: maximum drawdown, minimum number of observations, acceptable slippage, and how far live behavior may drift from the backtest. Do not optimize during this stage. If the strategy fails, record the failure. A rejected idea is useful evidence; a secretly modified idea is not."),
    ("checklist", 37.590896, "Your finished evidence package should contain the original hypothesis, timestamped rules, data sources, realistic cost assumptions, a complete experiment log, in sample and out of sample results, confidence intervals, multiple testing correction, walk-forward results, robustness tests, and forward paper trading evidence. Statistical significance is only one gate. The strategy must also be economically meaningful, executable, diversified, and small enough for its market capacity. Treat this process as scientific risk control, not a promise of profit."),
]


def chunk_text(text: str, limit: int = 360) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks, current = [], ""
    for sentence in sentences:
        candidate = sentence if not current else f"{current} {sentence}"
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks


def synth(kokoro: Kokoro, text: str, speed: float) -> tuple[np.ndarray, int]:
    chunks = chunk_text(text)
    pieces, sample_rate = [], None
    for index, chunk in enumerate(chunks):
        audio, sr = kokoro.create(chunk, voice=VOICE, speed=speed, lang=LANG)
        sample_rate = int(sr)
        pieces.append(np.asarray(audio, dtype=np.float32))
        if index + 1 < len(chunks):
            pieces.append(np.zeros(int(sample_rate * 0.10), dtype=np.float32))
    if sample_rate is None or not pieces:
        raise RuntimeError("Kokoro returned no audio")
    return np.concatenate(pieces), sample_rate


def main() -> None:
    kokoro = Kokoro(MODEL, VOICES)
    manifest = {"engine": "Kokoro", "voice": VOICE, "language": LANG, "scenes": []}
    for scene_id, target, text in SCENES:
        probe, sr = synth(kokoro, text, 1.0)
        probe_duration = len(probe) / sr
        speed = min(1.35, max(0.75, probe_duration / target))
        final, sr = synth(kokoro, text, speed)
        final_duration = len(final) / sr
        path = OUT / f"{scene_id}.wav"
        sf.write(path, final, sr, subtype="PCM_16")
        record = {"id": scene_id, "target_duration": target, "probe_duration": probe_duration, "kokoro_speed": speed, "final_duration": final_duration, "sample_rate": sr, "file": path.name}
        manifest["scenes"].append(record)
        print(json.dumps(record), flush=True)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
