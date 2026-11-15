"""Explicitly publish a complete collection; Cloudflare remains the independent fallback."""
import json
import os
from recover_automation import GitHub, REPOSITORY
from wecom_cloud import report_from_checkout, require_complete_collection


def main():
    if os.environ.get('GITHUB_REPOSITORY') != REPOSITORY:
        raise RuntimeError('Unexpected repository')
    report=require_complete_collection(report_from_checkout(), expected_run=os.environ['GITHUB_RUN_ID'])
    github=GitHub(os.environ['GITHUB_TOKEN'])
    dispatched,errors=[],[]
    for workflow,inputs in [('wecom-notify.yml',{'action':'recover'}),('pages.yml',{})]:
        try:
            github.api('POST','actions/workflows/'+workflow+'/dispatches',{'ref':'main','inputs':inputs})
            dispatched.append(workflow)
        except Exception as exc:
            errors.append(workflow+': '+type(exc).__name__)
    print(json.dumps({'collection_run':report['collection_run'],'dispatched':dispatched,'errors':errors}))
    if errors:
        raise RuntimeError('Some output workflows were not dispatched; independent recovery remains enabled')


if __name__=='__main__':
    main()
