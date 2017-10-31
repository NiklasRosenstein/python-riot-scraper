"""
Command-line tool and library to scrape the RiotGames matchlist API.
"""

from __future__ import print_function, division

import argparse
import datetime
import io
import json
import os
import requests
import riotwatcher
import sys
import time

json.JSONDecodeError


class Store(object):
  """
  Interface for storing match information.
  """

  def suggest_search_intervals(self, account_id):
    """
    Suggest search intervals for matches of the specified *account_id*. A list
    of time intervals must be returned. Every time interval is a pair of
    values, the begin and end time of that interval. A time value may be #None
    to indicate that the search should continue indefinitely in that direction
    of the timeline.
    """

    return [(None, None)]

  def has_match(self, match_id, timestamp):
    """
    Return #True if the store already has information about the match
    identified by *match_id*. In that case, the match information is not
    requested again.
    """

    raise NotImplementedError

  def store_match(self, match_id, timestamp, match, timeline):
    """
    Store the match information as a JSON object *match*. Note that the
    *match_id* is also present as `match['gameId']`. Note that timeline
    information may not be requested during the scraping process, in which
    case #None is passed for the *timeline* parameter. If there simply is
    not timeline information available for a match, an empty dictionary will
    be passed instead.
    """

    raise NotImplementedError


def scrape(store, api_key, region, summoner_name, empty_weeks_to_stop=10,
           with_timeline=False, progress_callback=NotImplemented):
  """
  Scrape the matchlist and save all matches in *store*.

  progress_callback (function): See #scrape_default_progress_callback().
  """

  watcher = riotwatcher.RiotWatcher(api_key)
  summoner = watcher.summoner.by_name(region, summoner_name)

  if progress_callback is NotImplemented:
    progress_callback = scrape_default_progress_callback

  # The Riot API only allows a time interval of one week, thus we
  # have to find the matches in chunks of one week.
  one_week = 1000 * 3600 * 24 * 7

  user_abort = False
  for interval in store.suggest_search_intervals(summoner['accountId']):
    if user_abort: break
    if interval[1] is None:
      interval = (interval[0], int(time.time() * 1000))                         # TODO: that region's current time
    empty_weeks_passed = 0
    while empty_weeks_passed < empty_weeks_to_stop:
      begin_time = interval[1] - one_week
      if interval[0] and begin_time < interval[0]:
        begin_time = interval[0]
      try:
        matches = watcher.match.matchlist_by_account(
          region, summoner['accountId'], begin_time=begin_time,
          end_time=interval[1])['matches']
      except requests.HTTPError as e:
        if e.response.status_code != 404:  # no matches found
          raise
      interval = (interval[0], begin_time)  # shrink the interval
      if not matches:
        empty_weeks_passed += 1
        continue
      # Sort by newest first, for consistency with lookback order and the
      # FileStore --continuous option.
      matches.sort(key=lambda x: -x['timestamp'])
      if progress_callback:
        event_data = {'beginTime': begin_time, 'matchCount': len(matches)}
        if progress_callback('matchlist', event_data) is False:
          user_abort = True
          break
      empty_weeks_passed = 0
      for index, match_info in enumerate(matches):
        if store.has_match(match_info['gameId'], match_info['timestamp']):
          continue
        if progress_callback:
          event_data = {'matchIndex': index, 'matchCount': len(matches)}
          if progress_callback('match', event_data) is False:
            user_abort = True
            break
        match_data = watcher.match.by_id(region, match_info['gameId'])
        timeline = None
        if with_timeline:
          timeline = watcher.match.timeline_by_match(region, match_info['gameId'])
        store.store_match(
          match_info['gameId'],
          match_info['timestamp'],
          match_data,
          timeline
        )

  return not user_abort


def scrape_default_progress_callback(event, data):
  """
  Default progress callback for the #scrape() function.

  # Event: `'matchlist'`
  Data contains the `beginTime` and `matchCount`.

  # Event: `'match'`
  Data contains the `matchIndex` and `matchCount`.

  If the progress method returns #False, the #scrape() function will abort
  and return #False. Note that the return value must be exactly #False, not
  just a "falsy" value.
  """

  if event == 'matchlist':
    date = datetime.datetime.fromtimestamp(data['beginTime'] / 1000)
    print('Found {} matches in week {}'.format(data['matchCount'], date))
  elif event == 'match':
    print('  downloading match {}/{}'.format(data['matchIndex']+1, data['matchCount']))


class FileStore(Store):
  """
  Store matches in JSONLine formatted file.
  """

  def __init__(self, file, append=False, close=True, continuous=False):
    if isinstance(file, str):
      file = open(file, 'a+' if append else 'w+')
    self._file = file
    self._close = close
    self._matches = set()
    self._mintime = None
    self._maxtime = None
    self._has_newline = True
    self._continuous = continuous

    if append:
      pos = file.tell()
      file.seek(0)
      for index, line in enumerate(l.strip() for l in file):
        if not line: continue
        try:
          match = json.loads(line)
        except json.JSONDecodeError as e:
          raise ValueError('invalid JSON at line {}: {}'.format(index+1, e))
        if self._mintime is None or match['gameCreation'] < self._mintime:
          self._mintime = match['gameCreation']
        if self._maxtime is None or match['gameCreation'] > self._maxtime:
          self._maxtime = match['gameCreation']
        self._matches.add(match['gameId'])

      # Check if the file has a newline at the end.
      file.seek(0, os.SEEK_END)
      file.seek(file.tell() - 1)
      if file.read(1) != '\n':
        self._has_newline = False
      file.seek(pos)

  def suggest_search_intervals(self, account_id):
    if self._continuous and self._matches:
      return [(None, self._mintime), (self._maxtime, None)]
    return [(None, None)]

  def has_match(self, match_id, timestamp):
    return match_id in self._matches

  def store_match(self, match_id, timestamp, match_data, timeline):
    if not self._has_newline:
      self._file.write('\n')
      self._has_newline = True
    match_data['timeline'] = timeline
    self._file.write(json.dumps(match_data))
    self._file.write('\n')
    self._file.flush()
    self._matches.add(match_id)


parser = argparse.ArgumentParser()
parser.add_argument('api_key')
parser.add_argument('summoner',
  help='In the form of <region>:<summoner_name>')
parser.add_argument('--with-timeline', action='store_true',
  help='Retrieve timeline information for every match (if available).')
parser.add_argument('--output',
  help='Output filename. Defaults to <summoner_name>.jsonl')
parser.add_argument('--append', action='store_true',
  help='Recognize existing matches in the output file and append new entries.')
parser.add_argument('--cont', '--continuous', action='store_true',
  help='Assume that matches in the output file are continuous. This is '
       'enabled by default if --output is not specified, because it assumes '
       'that only matches for a specific summoner are being downloaded.')

def main():
  args = parser.parse_args()
  if not args.output and args.append:
    print('assuming existing data is continuous.')
    args.continuous = True
  region, summoner_name = args.summoner.partition(':')[::2]
  if not region or not summoner_name:
    print('error: second positional argument must be of the format ')
    print('       <region>:<summoner_name>, got "{}"'.format(args.summoner))
    return 1
  if not args.output:
    args.output = summoner_name + '.jsonl'
  if args.append:
    print('reading existing data...')
  store = FileStore(args.output, append=args.append,
    continuous=args.continuous)
  scrape(store, args.api_key, region, summoner_name,
    with_timeline=args.with_timeline)


if __name__ == '__main__':
  sys.exit(main())
