"""Immutable run manifests and one usage record per actual model invocation."""
from datetime import datetime, timezone
from decimal import Decimal
from time import monotonic
from uuid import uuid4, uuid5, NAMESPACE_URL
from app.outfits.config import digest
from app.outfits.diagnostics import error_details


def run_manifest(uid, jobs, config):
    from app.core.runtime_snapshot import runtime_config_snapshot
    snapshot = runtime_config_snapshot(config).model_dump()
    return {'id':str(uuid5(NAMESPACE_URL,digest(['outfit-run-v1',uid,config.generation_key,sorted(j['id'] for j in jobs)]))),
            'user_id':uid,'algorithm':'clothing_accessories_full_review_v1','generation_key':config.generation_key,
            'evaluator_key':config.evaluator_key,'generation_model':config.generation_model,
            'evaluation_model':config.evaluation_model,
            'generation_prompt_hash':digest(config.clothing_text if config.footwear_pipeline else config.generation_text),'evaluation_prompt_hash':digest(config.evaluation_text),
            'config':{**config.snapshot(), 'runtime_snapshot': snapshot},'pinned':False}


def usage_fields(usage, rates):
    def count(value):
        return value if isinstance(value,int) and not isinstance(value,bool) and value>=0 else None
    incoming=count(usage.get('input_tokens')); outgoing=count(usage.get('output_tokens'))
    cached=count((usage.get('input_tokens_details') or {}).get('cached_tokens',0))
    cost=None
    if rates and incoming is not None and outgoing is not None and cached is not None and cached<=incoming:
        cost=(Decimal(incoming-cached)*Decimal(str(rates['input_per_million']))+
              Decimal(cached)*Decimal(str(rates['cached_input_per_million']))+
              Decimal(outgoing)*Decimal(str(rates['output_per_million'])))/Decimal(1_000_000)
    return {'input_tokens':incoming,'output_tokens':outgoing,'cached_input_tokens':cached,
            'estimated_cost_usd':str(cost) if cost is not None else None,'raw_usage':usage or None}


def tracked_call(store, job, run, stage, model, invoke, phase=None):
    call={'id':str(uuid4()),'run_id':run['id'],'job_id':job['id'],'user_id':job['user_id'],
          'attempt':job['attempts'],'lease_token':job.get('lease_token'),'stage':stage,'model':model,
          'status':'running','diagnostics':{'phase':phase or stage},'pricing':run['config'].get('pricing',{}).get(model)}
    store.start_call(call)  # Fail closed before spending if accounting is unavailable.
    start=monotonic()
    try:
        result,usage=invoke()
    except Exception as exc:
        exc.outfit_phase = phase or stage
        # A network error may occur after provider billing. Never count it as zero cost.
        store.finish_call(call['id'],{'status':'failed','error_type':type(exc).__name__, 'diagnostics':error_details(exc),
            'duration_ms':round((monotonic()-start)*1000),'finished_at':datetime.now(timezone.utc).isoformat()})
        raise
    store.finish_call(call['id'],{'status':'succeeded','duration_ms':round((monotonic()-start)*1000),
        'finished_at':datetime.now(timezone.utc).isoformat(),**usage_fields(usage,call['pricing'])})
    return result,usage,call['id']
