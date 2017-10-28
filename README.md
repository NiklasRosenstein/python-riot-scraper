## riot-scraper

A library and command-line interface to scrape the RiotGames matchlist API
into JSONLines format. The scraping process can be aborted and continued at
arbitrary times.

#### Usage

Download the matchlist of a summoner via the command-line:

```
$ python3 riot_scraper.py <RiotApiKey> euw1:FadingFaces --append --with-timeline
```

Doing the same with the Python API:

```python
import riot_scraper
store = riot_scraper.FileStore('FadingFaces.jsonl', append=True)
riot_scraper.scrape(
  store,
  '<RiotApiKey>',
  'euw1',
  'FadingFaces'.
  with_timeline=True
)
```

> Note that for large amounts of scraping work, I suggest you implement a
> custom `riot_scraper.Store` class that instead communicates with a real
> database instead of dumping everything to a single file.
> 
> The order of matches in the output file are in no particular order.

#### Dependencies

* [Riot-Watcher](https://github.com/pseudonym117/Riot-Watcher)
