"""Synthesize a complete result with the installed model SDK."""
from pathlib import Path
import argparse
import soundfile as sf
from pandora_qwen3_tts_12hz_0_6b_customvoice import TTSModel
from _lifecycle import managed_owner, ExampleInterrupted, cpu_placement, runtime_kwargs
TEXTS = {
    "zh": "你好，欢迎使用语音合成。今天，我们用清晰自然的声音，把文字变成可以听见的表达。",
    "en": "Hello, welcome to text-to-speech. Today, we use a clear and natural voice to turn written words into speech you can hear.",
}
def arguments():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--models",default=str(Path(__file__).resolve().parents[2]/"models"))
    p.add_argument("--language",choices=TEXTS,default="en")
    p.add_argument("--speaker")
    p.add_argument("--text")
    p.add_argument("--out",default="speech.wav")
    p.add_argument("--cpu-affinity", type=cpu_placement, help="override SDK CPU placement")
    return p
def main():
    a=arguments().parse_args()
    with runtime_kwargs(a.cpu_affinity) as kwargs, managed_owner(
        TTSModel.from_pretrained, a.models, **kwargs
    ) as (model, stop):
        result=model.synthesize(a.text or TEXTS[a.language],speaker=a.speaker or ("vivian" if a.language=="zh" else "ryan"),language=a.language)
        stop.check()
        sf.write(a.out,result.audio,result.sample_rate)
        print(f"{a.out}: {result.duration_s:.2f}s, finish_reason={result.finish_reason}")
if __name__=="__main__":
    try: main()
    except ExampleInterrupted as exc: raise SystemExit(128+exc.signum)
