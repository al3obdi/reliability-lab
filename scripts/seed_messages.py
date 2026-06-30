"""Seed the pipeline with Arabic sample messages.

Usage:
    python scripts/seed_messages.py --count 100
    python scripts/seed_messages.py --count 50 --batch 10
"""

import argparse
import sys
import time
import uuid
import httpx

SAMPLE_TEXTS = [
    "مرحبا، أريد الاستفسار عن طلبي رقم ٥٥٣٢",
    "السلام عليكم، هل يمكنني تغيير موعد التسليم؟",
    "أريد إلغاء الطلب رقم ١٢٣٤ من فضلك",
    "شكرا على الخدمة الممتازة، وصل الطلب قبل الموعد",
    "هل يوجد توصيل إلى مدينة الرياض؟",
    "أريد تتبع الشحنة رقم ٧٨٩٠",
    "الفاتورة غير صحيحة، المبلغ المدفوع أكثر من المطلوب",
    "متى يصل مندوب التوصيل؟ أنا في انتظاره منذ ساعة",
    "المنتج وصل تالف، أريد استبداله أو استرداد المبلغ",
    "هل تقبلون الدفع عند الاستلام؟",
    "أريد تغيير عنوان التوصيل إلى حي النزهة",
    "كم المدة المتوقعة للتوصيل داخل جدة؟",
    "الطلب رقم ٤٤٥٥ لم يصل بعد، مضى عليه ٥ أيام",
    "هل يمكنني إضافة منتج آخر للطلب قبل الشحن؟",
    "شكرا جزيلا، التجربة كانت رائعة وسأكرر الطلب",
]

CHANNELS = ["web", "mobile", "email", "whatsapp"]


def main():
    parser = argparse.ArgumentParser(description="Seed the pipeline with Arabic messages")
    parser.add_argument("--count", type=int, default=100, help="Number of messages to publish")
    parser.add_argument("--batch", type=int, default=20, help="Batch size for progress reporting")
    parser.add_argument("--api", type=str, default="http://localhost:8000", help="API base URL")
    args = parser.parse_args()

    url = f"{args.api}/api/v1/messages"
    published = 0
    duplicates = 0
    failures = 0
    start = time.monotonic()

    for i in range(args.count):
        payload = {
            "message_id": str(uuid.uuid4()),
            "customer_id": f"cust-{(i % 50):04d}",
            "text": SAMPLE_TEXTS[i % len(SAMPLE_TEXTS)],
            "channel": CHANNELS[i % len(CHANNELS)],
        }
        try:
            r = httpx.post(url, json=payload, timeout=10)
            if r.status_code == 202:
                data = r.json()
                if data.get("duplicate"):
                    duplicates += 1
                else:
                    published += 1
            else:
                failures += 1
                print(f"  [{i+1}] HTTP {r.status_code}: {r.text[:100]}", flush=True)
        except Exception as exc:
            failures += 1
            print(f"  [{i+1}] Error: {exc}", flush=True)

        if (i + 1) % args.batch == 0:
            elapsed = time.monotonic() - start
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            print(f"  [{i+1}/{args.count}] published={published} duplicates={duplicates} "
                  f"failures={failures} rate={rate:.1f}/s", flush=True)

    elapsed = time.monotonic() - start
    rate = args.count / elapsed if elapsed > 0 else 0
    print(f"\nDone: {args.count} messages in {elapsed:.1f}s ({rate:.1f}/s)")
    print(f"  Published:  {published}")
    print(f"  Duplicates: {duplicates}")
    print(f"  Failures:   {failures}")


if __name__ == "__main__":
    main()
