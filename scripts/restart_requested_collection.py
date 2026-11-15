"""One explicit, auditable cancellation/restart request; no independent schedule."""
import json
import os
from pathlib import Path
import time
from recover_automation import GitHub, REPOSITORY


def main():
    if os.environ.get('GITHUB_REPOSITORY') != REPOSITORY:
        raise RuntimeError('Unexpected repository')
    request=json.loads((Path(__file__).resolve().parents[1]/'.github/restart-collection-request.json').read_text())
    run_id=str(request['run_id'])
    if not run_id.isdigit():
        raise ValueError('Invalid requested run ID')
    github=GitHub(os.environ['GH_TOKEN'])
    path='actions/runs/'+run_id
    run=github.api('GET',path)
    if run.get('path')!='.github/workflows/scheduled-refresh.yml' or run.get('head_branch')!='main':
        raise RuntimeError('Requested run is not the main collection workflow')
    if run['status']!='completed':
        github.api('POST',path+'/cancel')
        for attempt in range(36):
            if github.api('GET',path)['status']=='completed':
                break
            time.sleep(5)
        else:
            raise RuntimeError('Cancellation is still pending; do not dispatch a concurrent collection')
    github.api('POST','actions/workflows/scheduled-refresh.yml/dispatches',{'ref':'main','inputs':{'catch_up':True}})
    print(json.dumps({'status':'recovery_dispatched','previous_run':run_id,'deduplication':'preserved'}))


if __name__=='__main__':
    main()
