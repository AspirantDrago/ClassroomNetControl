import json, subprocess, tempfile, shutil, unittest
from pathlib import Path
from datetime import datetime, timezone
from cmnc_camera_service import main as camera

@unittest.skipUnless(shutil.which("ffmpeg"), "native FFmpeg required")
class NativeHlsTests(unittest.TestCase):
    def test_timestamps_and_worker_restart_continuity(self):
        with tempfile.TemporaryDirectory(prefix='cmnc-hls-check-') as folder:
            stream=camera.SharedCameraStream(id='test',key='test',rtsp_url='rtsp://unused.invalid',quality='sub',hls_dir=Path(folder),created_at=datetime.now(timezone.utc))
            seen=set()
            for generation in range(4):
                stream.generation=generation
                original=camera.build_ffmpeg_command(stream)
                tail=original[original.index('-i')+2:]
                tail=[('1:a:0' if arg=='0:a:0?' else arg) for arg in tail]
                prefix=['ffmpeg','-hide_banner','-loglevel','warning','-f','lavfi','-i',r'testsrc2=size=320x180:rate=25:duration=2,setpts=PTS+if(gte(N\,25)\,3600/TB\,0)',
                        '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=2']
                result=subprocess.run(prefix+tail,capture_output=True,text=True,timeout=20)
                assert result.returncode==0,result.stderr
                assert 'Non-monotonic' not in result.stderr,result.stderr
                playlist=Path(folder,'index.m3u8').read_text()
                durations=[float(line.split(':')[1].rstrip(',')) for line in playlist.splitlines() if line.startswith('#EXTINF:')]
                assert max(durations)<5,durations
                created={p.name for p in Path(folder).glob(f'segment_{generation:08d}_*.ts')}
                assert created and not(seen&created)
                seen.update(created)
            assert '#EXT-X-DISCONTINUITY' in playlist
