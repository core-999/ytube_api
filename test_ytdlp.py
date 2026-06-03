import yt_dlp
ydl_opts = {'quiet': True, 'extract_flat': True, 'default_search': 'ytsearch1'}
with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    info = ydl.extract_info("never gonna give you up", download=False)
    print(info['entries'][0]['id'])
