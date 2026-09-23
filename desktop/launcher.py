"""本地一键启动器；只监听回环地址，首次产生随机令牌并通过 URL fragment 配对。"""
from pathlib import Path
import os,secrets,threading,webbrowser,argparse
import uvicorn
from evovid.server import create_app
from evovid.config import load_local_config

def main():
    """--lan 需显式使用：仅限可信局域网，公网部署必须另配 HTTPS。"""
    load_local_config(Path(__file__).parent/'config.local.env')
    parser=argparse.ArgumentParser();parser.add_argument('--profile',choices=['rise','opencv','pocket'],default='rise')
    parser.add_argument('--no-browser',action='store_true');parser.add_argument('--lan',action='store_true')
    parser.add_argument('--port',type=int,default=8080);args=parser.parse_args()
    if not 1024<=args.port<=65535:parser.error('port must be 1024..65535')
    home=Path(os.getenv('EVOVID_HOME',str(Path(__file__).parent/'.evovid')));home.mkdir(exist_ok=True,parents=True)
    keyfile=home/'access-token.txt'
    if not keyfile.exists():
        keyfile.write_text(secrets.token_urlsafe(32),encoding='utf-8')
        try:keyfile.chmod(0o600)
        except OSError:pass
    token=keyfile.read_text().strip()
    if len(token)<32:raise RuntimeError('Invalid token file; remove it to generate a fresh token.')
    page='review.html' if args.profile=='opencv' else ''
    url=f'http://127.0.0.1:{args.port}/{page}#key={token}&profile={args.profile}'
    print('EvoVid: '+url,flush=True)
    print('Local pairing token (do not publish): '+token,flush=True)
    if args.lan:print('LAN enabled. This HTTP server is for trusted private networks only; do not expose to the Internet.')
    if not args.no_browser:threading.Timer(1.2,lambda:webbrowser.open(url)).start()
    uvicorn.run(create_app(home,token),host='0.0.0.0' if args.lan else '127.0.0.1',port=args.port,log_level='warning',access_log=False)
if __name__=='__main__':main()
