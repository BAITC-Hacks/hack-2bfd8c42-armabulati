import httpx
import pytest
from app.analysis import complete_stream


def test_stream_collects_content_and_requires_final_stop():
    body = 'data: {"choices":[{"delta":{"content":"{\\"ok\\":true}"},"finish_reason":null}]}\n\ndata: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200,text=body)),base_url='http://localhost') as client:
        assert complete_stream(client,{},lambda size:None)=='{"ok":true}'


@pytest.mark.parametrize('reason', ['length', None])
def test_stream_rejects_truncated_completion(reason):
    import json
    body='data: '+json.dumps({'choices':[{'delta':{'content':'{'},'finish_reason':reason}]})+'\n\ndata: [DONE]\n'
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,text=body)),base_url='http://localhost') as client:
        with pytest.raises(RuntimeError):
            complete_stream(client,{},lambda size:None)
