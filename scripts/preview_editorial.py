"""Generate local editorial previews only. This script never sends any messages."""
import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kap_bot

parser = argparse.ArgumentParser()
parser.add_argument("ids", type=int, nargs="+")
args = parser.parse_args()
kap_bot.load_env()
output = kap_bot.ROOT / "output/editorial"
output.mkdir(parents=True, exist_ok=True)
for ident in args.ids:
    record = kap_bot.PublicKapClient().detail(ident)
    if record is None:
        print(ident, "KAP kaydı bulunamadı", flush=True)
        continue
    _, detail = record
    report = kap_bot.editorial_report(detail)
    if report["status"] == "ready":
        article = report["article"]
        try:
            image = kap_bot.render_event_card(article["category"], article["headline"], dict(detail, editorial=article))
            target = output / f"{ident}.png"
            shutil.move(image, target)
            report["preview"] = str(target)
        except ValueError as error:
            report["status"], report["reason"] = "review", str(error)
    (output / f"{ident}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(ident, report["status"], report.get("tweet", report["reason"]), report.get("preview", ""), flush=True)
