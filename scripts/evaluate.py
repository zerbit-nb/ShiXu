"""Save real model results for human evaluation; never creates tasks."""
import argparse
import asyncio
from datetime import datetime
import json
import hashlib
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.services.extraction import normalize_extraction
from app.services.llm_service import LLMService, SYSTEM_PROMPT, local_extraction_schema


async def run(args):
    settings=Settings();settings.load(ROOT/'config.local.json')
    if settings.provider!='local' and not args.allow_cloud:
        raise SystemExit('当前选择云端服务。确认发送自编样例与可能产生费用后，使用 --allow-cloud。')
    cases=json.loads((ROOT/'tests/fixtures/notifications.json').read_text(encoding='utf-8'))[:args.limit]
    report={'provider':settings.provider,'model':settings.llm_model,'created_at':datetime.now().isoformat(),'results':[],'note':'任务数与按顺序比对的日期仅为诊断，语义精确率、召回率和字段正确性仍需人工核对。'}
    report.update(prompt_sha256=hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(), temperature=0.1, max_tokens=4000, timeout_seconds=settings.llm_timeout_seconds, schema_sha256=hashlib.sha256(json.dumps(local_extraction_schema(),sort_keys=True).encode()).hexdigest())
    service=LLMService(settings)
    for case in cases:
        started=time.monotonic();item={'id':case['id'],'expected':case['expected_tasks']}
        try:
            raw=await service.extract({'raw_text':case['raw_text'],'sent_at':case['sent_at']})
            drafts=normalize_extraction(raw,datetime.fromisoformat(case['sent_at']) if case['sent_at'] else None, case['raw_text'])
            item.update(output=raw,drafts=drafts,task_count_matches=len(drafts)==len(case['expected_tasks']),ordered_dates_match=[d['fields']['deadline'] for d in drafts]==[t['deadline'] for t in case['expected_tasks']])
        except Exception as exc:
            # No API response bodies, credential-bearing headers, or URLs are logged.
            item['error_type']=type(exc).__name__
        item['seconds']=round(time.monotonic()-started,2);report['results'].append(item)
        print(f"{case['id']}: {'error '+item['error_type'] if 'error_type' in item else 'captured'} ({item['seconds']}s)")
        if 'error_type' in item and item['error_type'] in {'ConnectError','HTTPStatusError','RuntimeError'}:break
    output=ROOT/'data/evaluations';output.mkdir(parents=True,exist_ok=True)
    path=output/f"{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Report saved: {path}')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-cloud',action='store_true')
    parser.add_argument('--limit',type=int,default=24)
    args=parser.parse_args()
    if not 1<=args.limit<=24:parser.error('--limit must be between 1 and 24')
    asyncio.run(run(args))
