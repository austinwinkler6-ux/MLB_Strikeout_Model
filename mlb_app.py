import streamlit as st
import requests
import pandas as pd
from datetime import date, timedelta, datetime
from io import StringIO
from supabase import create_client, Client
from nba_api.stats.endpoints import playergamelog, leaguedashplayerstats, leaguedashteamstats
from nba_api.stats.static import players as nba_players

st.set_page_config(page_title="Model Metrics", page_icon="⚾", layout="wide")

ODDS_API_KEY = st.secrets["ODDS_API_KEY"]
ADMIN_EMAIL = "austinwinkler6@icloud.com"

# ---- SUPABASE CONNECTION ----
@st.cache_resource
def get_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = get_supabase()

# ---- AUTH FUNCTIONS ----
def sign_up(email, password):
    try:
        res = supabase.auth.sign_up({"email": email, "password": password})
        return res.user, None
    except Exception as e:
        return None, str(e)

def sign_in(email, password):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        return res.user, res.session, None
    except Exception as e:
        return None, None, str(e)

def sign_out():
    try:
        supabase.auth.sign_out()
    except:
        pass
    st.session_state.clear()

# ---- AUTH WALL ----
if 'user' not in st.session_state:
    st.markdown("""
        <div style='text-align: center; padding-top: 60px;'>
            <img src='https://raw.githubusercontent.com/austinwinkler6-ux/mlb_strikeout_model/main/ModelMetricsLogo.png' width='225'/>
            <h2 style='margin-top: 20px;'>Welcome to Model Metrics</h2>
        </div>
    """, unsafe_allow_html=True)

    auth_tab1, auth_tab2 = st.tabs(["Login", "Sign Up"])

    with auth_tab1:
        login_email = st.text_input("Email", key="login_email")
        login_password = st.text_input("Password", type="password", key="login_password")
        if st.button("Login", use_container_width=True):
            user, session, error = sign_in(login_email, login_password)
            if error:
                st.error(f"Login failed: {error}")
            else:
                st.session_state['user'] = user
                st.session_state['session'] = session
                st.rerun()

    with auth_tab2:
        signup_email = st.text_input("Email", key="signup_email")
        signup_password = st.text_input("Password", type="password", key="signup_password")
        signup_password2 = st.text_input("Confirm Password", type="password", key="signup_password2")
        if st.button("Create Account", use_container_width=True):
            if signup_password != signup_password2:
                st.error("Passwords don't match!")
            elif len(signup_password) < 6:
                st.error("Password must be at least 6 characters!")
            else:
                user, error = sign_up(signup_email, signup_password)
                if error:
                    st.error(f"Sign up failed: {error}")
                else:
                    user2, session, error2 = sign_in(signup_email, signup_password)
                    if not error2:
                        st.session_state['user'] = user2
                        st.session_state['session'] = session
                        st.rerun()
    st.stop()

# ---- LOGGED IN ----
user = st.session_state['user']
user_id = user.id
is_admin = user.email.lower() == ADMIN_EMAIL.lower()

supabase.postgrest.auth(st.session_state['session'].access_token)

# ---- DATABASE FUNCTIONS ----
def load_bets(sport=None):
    try:
        query = supabase.table("bets").select("*").eq("user_id", user_id)
        if sport:
            query = query.eq("sport", sport)
        response = query.order("created_at", desc=True).execute()
        return response.data or []
    except:
        return []

def save_bet(bet):
    try:
        bet['user_id'] = user_id
        supabase.table("bets").insert(bet).execute()
    except Exception as e:
        st.error(f"Error saving bet: {e}")

def update_bet(bet_id, updates):
    try:
        supabase.table("bets").update(updates).eq("id", bet_id).eq("user_id", user_id).execute()
    except Exception as e:
        st.error(f"Error updating bet: {e}")

def delete_bet(bet_id):
    try:
        supabase.table("bets").delete().eq("id", bet_id).eq("user_id", user_id).execute()
    except Exception as e:
        st.error(f"Error deleting bet: {e}")

def load_predictions(sport=None):
    try:
        query = supabase.table("predictions").select("*").eq("user_id", user_id)
        if sport:
            query = query.eq("sport", sport)
        response = query.order("created_at", desc=True).execute()
        return response.data or []
    except:
        return []

def save_prediction(pred):
    try:
        pred['user_id'] = user_id
        supabase.table("predictions").insert(pred).execute()
    except Exception as e:
        st.error(f"Error saving prediction: {e}")

def update_prediction(pred_id, updates):
    try:
        supabase.table("predictions").update(updates).eq("id", pred_id).eq("user_id", user_id).execute()
    except Exception as e:
        st.error(f"Error updating prediction: {e}")

def calc_profit(bet_amount, odds, result):
    if result == 'Win':
        if odds > 0:
            return round(bet_amount * (odds / 100), 2)
        else:
            return round(bet_amount * (100 / abs(odds)), 2)
    elif result == 'Loss':
        return -bet_amount
    return 0.0

# ---- PARK FACTORS ----
park_factors = {
    'Los Angeles Angels': 0.97, 'Baltimore Orioles': 1.02, 'Boston Red Sox': 0.95,
    'Chicago White Sox': 1.01, 'Cleveland Guardians': 0.98, 'Detroit Tigers': 0.99,
    'Houston Astros': 1.03, 'Kansas City Royals': 0.96, 'Minnesota Twins': 1.02,
    'New York Yankees': 1.04, 'Athletics': 0.98, 'Seattle Mariners': 1.05,
    'Tampa Bay Rays': 1.01, 'Texas Rangers': 0.97, 'Toronto Blue Jays': 1.00,
    'Arizona Diamondbacks': 1.02, 'Atlanta Braves': 1.01, 'Chicago Cubs': 0.96,
    'Cincinnati Reds': 0.99, 'Colorado Rockies': 0.88, 'Los Angeles Dodgers': 1.03,
    'Miami Marlins': 1.00, 'Milwaukee Brewers': 1.01, 'New York Mets': 1.02,
    'Philadelphia Phillies': 0.98, 'Pittsburgh Pirates': 0.97, 'San Diego Padres': 1.04,
    'San Francisco Giants': 0.96, 'St. Louis Cardinals': 0.99, 'Washington Nationals': 1.00
}

# ---- NBA LOOKUP ----
nba_abbrev_to_name = {
    'ATL': 'Atlanta Hawks', 'BOS': 'Boston Celtics', 'BKN': 'Brooklyn Nets',
    'CHA': 'Charlotte Hornets', 'CHI': 'Chicago Bulls', 'CLE': 'Cleveland Cavaliers',
    'DAL': 'Dallas Mavericks', 'DEN': 'Denver Nuggets', 'DET': 'Detroit Pistons',
    'GSW': 'Golden State Warriors', 'HOU': 'Houston Rockets', 'IND': 'Indiana Pacers',
    'LAC': 'LA Clippers', 'LAL': 'Los Angeles Lakers', 'MEM': 'Memphis Grizzlies',
    'MIA': 'Miami Heat', 'MIL': 'Milwaukee Bucks', 'MIN': 'Minnesota Timberwolves',
    'NOP': 'New Orleans Pelicans', 'NYK': 'New York Knicks', 'OKC': 'Oklahoma City Thunder',
    'ORL': 'Orlando Magic', 'PHI': 'Philadelphia 76ers', 'PHX': 'Phoenix Suns',
    'POR': 'Portland Trail Blazers', 'SAC': 'Sacramento Kings', 'SAS': 'San Antonio Spurs',
    'TOR': 'Toronto Raptors', 'UTA': 'Utah Jazz', 'WAS': 'Washington Wizards'
}

nba_name_to_abbrev = {v: k for k, v in nba_abbrev_to_name.items()}

league_avg_def_rating = 114.0
league_avg_pace = 98.5
league_avg_team_score = 112.0

# ---- AUTO LOAD MLB PITCHERS ----
@st.cache_data(ttl=3600)
def get_all_pitchers():
    url = "https://statsapi.mlb.com/api/v1/sports/1/players?season=2026&gameType=R"
    response = requests.get(url)
    data = response.json()
    pitchers = []
    for player in data['people']:
        if player.get('primaryPosition', {}).get('code') == '1':
            pitchers.append(player['fullName'])
    return sorted(pitchers)

# ---- BATTER K% FROM SAVANT ----
@st.cache_data(ttl=3600)
def get_batter_k_pcts():
    url = "https://baseballsavant.mlb.com/leaderboard/custom?year=2026&type=batter&filter=&sort=4&sortDir=desc&min=10&selections=k_percent&chart=false&x=k_percent&y=k_percent&r=no&chartType=beeswarm&csv=true"
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(url, headers=headers)
    df = pd.read_csv(StringIO(response.text))
    df['full_name'] = df['last_name, first_name'].apply(lambda x: f"{x.split(', ')[1]} {x.split(', ')[0]}")
    df['k_pct'] = df['k_percent'] / 100
    return df[['full_name', 'k_pct', 'player_id']]

# ---- GET PITCHER INFO FROM SCHEDULE ----
@st.cache_data(ttl=1800)
def get_pitcher_game_info(pitcher_name, game_date=None):
    try:
        check_date = game_date or date.today().strftime('%Y-%m-%d')
        url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={check_date}&hydrate=probablePitcher"
        data = requests.get(url).json()
        if not data['dates']:
            return None, None, None
        for game in data['dates'][0]['games']:
            home = game['teams']['home']['team']['name']
            away = game['teams']['away']['team']['name']
            home_pitcher = game['teams']['home'].get('probablePitcher', {}).get('fullName', '')
            away_pitcher = game['teams']['away'].get('probablePitcher', {}).get('fullName', '')
            if pitcher_name.lower() == home_pitcher.lower():
                return home, away, home
            elif pitcher_name.lower() == away_pitcher.lower():
                return away, home, home
    except:
        pass
    return None, None, None

def fmt_odds(o):
    if o is None:
        return 'N/A'
    return f"+{o}" if o > 0 else str(o)

# ---- GET MLB STARTERS FOR A DATE ----
def get_starters_for_date(game_date_str):
    try:
        url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={game_date_str}&hydrate=probablePitcher,linescore"
        response = requests.get(url)
        data = response.json()
        starters = []
        for game in data['dates'][0]['games']:
            home = game['teams']['home']['team']['name']
            away = game['teams']['away']['team']['name']
            game_pk = game['gamePk']
            home_pitcher = game['teams']['home'].get('probablePitcher', {}).get('fullName')
            away_pitcher = game['teams']['away'].get('probablePitcher', {}).get('fullName')
            if home_pitcher:
                starters.append({'pitcher': home_pitcher, 'team': home, 'opponent': away, 'home_team': home, 'game_pk': game_pk})
            if away_pitcher:
                starters.append({'pitcher': away_pitcher, 'team': away, 'opponent': home, 'home_team': home, 'game_pk': game_pk})
        return starters
    except:
        return []

# ---- GET ACTUAL MLB STRIKEOUTS ----
def get_actual_strikeouts(game_pk, pitcher_name):
    try:
        url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
        response = requests.get(url)
        data = response.json()
        for side in ['home', 'away']:
            pitchers = data['teams'][side]['pitchers']
            for pid in pitchers:
                player = data['teams'][side]['players'].get(f'ID{pid}', {})
                name = player.get('person', {}).get('fullName', '')
                if name.lower() == pitcher_name.lower():
                    stats = player.get('stats', {}).get('pitching', {})
                    return stats.get('strikeOuts', None)
    except:
        pass
    return None

# ---- GET NBA GAMES FOR A DATE ----
def get_nba_games_for_date(game_date_str):
    try:
        url = f"https://stats.nba.com/stats/scoreboardV2?DayOffset=0&LeagueID=00&gameDate={game_date_str}"
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.nba.com'}
        response = requests.get(url, headers=headers)
        data = response.json()
        games = []
        game_header = data['resultSets'][0]
        headers_list = game_header['headers']
        rows = game_header['rowSet']
        for row in rows:
            game = dict(zip(headers_list, row))
            games.append({
                'game_id': game['GAME_ID'],
                'home_team_abbrev': game.get('HOME_TEAM_ABBREVIATION', ''),
                'away_team_abbrev': game.get('VISITOR_TEAM_ABBREVIATION', '')
            })
        return games
    except:
        return []

# ---- MLB PROJECTION ENGINE ----
def run_projection(pitcher_name, opponent_team, home_team, season, weather_adj=1.0, before_date=None,
                   use_umpire=True, use_park=True, use_lineup=True, use_pitch_count=True, use_total=True):
    try:
        league_avg_k_pct_vr = 0.222
        league_avg_k_pct_vl = 0.218
        league_avg_favor = 0.43

        search = requests.get(f"https://statsapi.mlb.com/api/v1/people/search?names={pitcher_name}&sportId=1")
        player_data = search.json()['people'][0]
        player_id = player_data['id']
        pitcher_hand = player_data['pitchHand']['code']

        season_url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season&group=pitching&season={season}&sportId=1"
        season_data = requests.get(season_url).json()
        season_stat = season_data['stats'][0]['splits'][0]['stat']

        season_k = int(season_stat['strikeOuts'])
        season_bf = int(season_stat['battersFaced'])
        season_k_pct = round(season_k / season_bf, 3)
        season_pitches_total = int(season_stat.get('numberOfPitches', 0))
        season_strikes = int(season_stat.get('strikes', 0))
        season_strike_pct = round(season_strikes / season_pitches_total, 3) if season_pitches_total > 0 else 0.65

        log_url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=gameLog&group=pitching&season={season}&sportId=1"
        log_data = requests.get(log_url).json()
        splits = log_data['stats'][0]['splits']

        games = []
        for game in splits:
            game_date = game['date']
            if before_date and game_date >= before_date:
                continue
            g = game['stat']
            pitches = int(g.get('numberOfPitches', 0))
            strikes = int(g.get('strikes', 0))
            ip = float(g['inningsPitched'])
            games.append({
                'date': game_date,
                'opponent': game['opponent']['name'],
                'strikeouts': int(g['strikeOuts']),
                'innings': ip,
                'batters_faced': int(g['battersFaced']),
                'pitches': pitches,
                'strike_pct': round(strikes / pitches, 3) if pitches > 0 else 0.65,
                'pitches_per_inning': round(pitches / ip, 2) if ip > 0 else 17.0
            })

        if len(games) < 3:
            return None

        df = pd.DataFrame(games)
        df = df.iloc[::-1].reset_index(drop=True)

        last5_avg_ip = round(df['innings'].head(5).mean(), 2)
        last10_avg_ip = round(df['innings'].head(10).mean(), 2)
        last3_avg_ip = round(df['innings'].head(3).mean(), 2)
        season_avg_ip = round(df['innings'].mean(), 2)
        season_avg_bf = round(df['batters_faced'].mean(), 2)
        last5_k_pct = round(df['strikeouts'].head(5).sum() / df['batters_faced'].head(5).sum(), 3)
        last10_k_pct = round(df['strikeouts'].head(10).sum() / df['batters_faced'].head(10).sum(), 3)
        recent_strike_pct = round(df['strike_pct'].head(5).mean(), 3)

        last10_strikeouts = df['strikeouts'].head(10)
        last10_k_avg = round(last10_strikeouts.mean(), 2)
        last10_k_std = round(last10_strikeouts.std(), 2) if len(last10_strikeouts) > 1 else 0.0
        cv = round(last10_k_std / last10_k_avg, 3) if last10_k_avg > 0 else 1.0

        if cv < 0.20:
            confidence_tier = "🟢 Elite Stability"
        elif cv < 0.35:
            confidence_tier = "🟡 Normal"
        elif cv < 0.50:
            confidence_tier = "🟠 High Variance"
        else:
            confidence_tier = "🔴 Pass Candidate"

        last3_pitches = round(df['pitches'].head(3).mean(), 1)
        last10_pitches = round(df['pitches'].head(10).mean(), 1)
        season_avg_pitches = round(df['pitches'].mean(), 1)
        career_high_pitches = df['pitches'].max()
        pitches_per_inning = round(df['pitches_per_inning'].head(10).mean(), 2)

        if use_pitch_count:
            expected_pitch_count = round(
                (season_avg_pitches * 0.30) +
                (last10_pitches * 0.30) +
                (last3_pitches * 0.40), 1
            )
            if last3_pitches < season_avg_pitches * 0.80:
                expected_pitch_count = min(expected_pitch_count, last3_pitches * 1.05)
            elif last3_pitches > season_avg_pitches * 1.10:
                expected_pitch_count = min(expected_pitch_count * 1.05, career_high_pitches)
            elif len(df) > 0 and df['pitches'].iloc[0] > season_avg_pitches * 1.15:
                expected_pitch_count = min(expected_pitch_count, season_avg_pitches)
            pitch_based_ip = round(expected_pitch_count / pitches_per_inning, 2)
        else:
            expected_pitch_count = season_avg_pitches
            pitch_based_ip = season_avg_ip

        pitcher_skill = round(
            (season_k_pct * 0.70) +
            (last10_k_pct * 0.15) +
            (last5_k_pct * 0.15), 3
        )

        last3_starter = (last3_avg_ip >= 4.8) or (sum(df['innings'].head(3) >= 5.0) >= 2)

        if last3_starter:
            ip_season_w, ip_last10_w, ip_last5_w = 0.20, 0.30, 0.50
        elif last5_avg_ip > season_avg_ip * 1.5 or last5_avg_ip < season_avg_ip * 0.6:
            ip_season_w, ip_last10_w, ip_last5_w = 0.20, 0.30, 0.50
        else:
            ip_season_w, ip_last10_w, ip_last5_w = 0.30, 0.40, 0.30

        innings_formula = round(
            (season_avg_ip * ip_season_w) +
            (last10_avg_ip * ip_last10_w) +
            (last5_avg_ip * ip_last5_w), 2
        )
        expected_innings = round(min(innings_formula, pitch_based_ip), 2)
        expected_bf = round(expected_innings * (season_avg_bf / season_avg_ip), 1)

        velo_factor = round(1.0 + ((recent_strike_pct - season_strike_pct) * 0.8), 3)

        league_avg_k_pct = league_avg_k_pct_vr if pitcher_hand == 'R' else league_avg_k_pct_vl
        team_url = f"https://statsapi.mlb.com/api/v1/teams/stats?stats=season&group=hitting&season={season}&sportId=1"
        team_data = requests.get(team_url).json()

        opp_k_pct = None
        for split in team_data['stats'][0]['splits']:
            if split['team']['name'] == opponent_team:
                k = int(split['stat']['strikeOuts'])
                pa = int(split['stat']['plateAppearances'])
                opp_k_pct = round(k / pa, 3)
                break

        final_opp_k_pct = opp_k_pct or league_avg_k_pct

        lineup_k_pct = None
        if use_lineup:
            try:
                k_df = get_batter_k_pcts()
                check_date = before_date or date.today().strftime('%Y-%m-%d')
                sched_url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={check_date}&hydrate=lineups"
                sched_data = requests.get(sched_url).json()

                if sched_data.get('dates'):
                    for game in sched_data['dates'][0]['games']:
                        ht = game['teams']['home']['team']['name']
                        at = game['teams']['away']['team']['name']
                        if home_team in ht or home_team in at:
                            lineups = game.get('lineups', {})
                            if lineups:
                                if opponent_team in at:
                                    batting_lineup = lineups.get('awayPlayers', [])
                                else:
                                    batting_lineup = lineups.get('homePlayers', [])
                                total = 0
                                count = 0
                                for player in batting_lineup[:9]:
                                    name = player['fullName']
                                    match = k_df[k_df['full_name'].str.lower() == name.lower()]
                                    if not match.empty:
                                        total += match['k_pct'].iloc[0]
                                        count += 1
                                if count >= 5:
                                    lineup_k_pct = round(total / count, 3)
                            break

                if lineup_k_pct and lineup_k_pct > 0:
                    final_opp_k_pct = round((lineup_k_pct * 0.60) + (final_opp_k_pct * 0.40), 3)
            except:
                pass

        opp_factor = round(final_opp_k_pct / league_avg_k_pct, 3)
        park_factor = park_factors.get(home_team, 1.0) if use_park else 1.0

        umpire_factor = 1.0
        umpire_name = None
        if use_umpire:
            try:
                check_date = before_date or date.today().strftime('%Y-%m-%d')
                sched_url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={check_date}&hydrate=officials"
                sched_data = requests.get(sched_url).json()
                if sched_data.get('dates'):
                    for game in sched_data['dates'][0]['games']:
                        ht = game['teams']['home']['team']['name']
                        at = game['teams']['away']['team']['name']
                        if home_team in ht or home_team in at:
                            for official in game.get('officials', []):
                                if official['officialType'] == 'Home Plate':
                                    umpire_name = official['official']['fullName']
                            break
                if umpire_name:
                    ump_data = requests.get("https://umpscorecards.com/api/umpires", headers={'User-Agent': 'Mozilla/5.0'}).json()
                    for ump in ump_data['rows']:
                        if ump['umpire'].lower() == umpire_name.lower():
                            umpire_favor = round(ump['favor_abs_mean'], 3)
                            umpire_factor = round(1.0 + ((umpire_favor - league_avg_favor) * 0.5), 3)
                            umpire_factor = max(0.97, min(1.03, umpire_factor))
                            break
            except:
                pass

        total_factor = 1.0
        if use_total:
            try:
                if before_date:
                    hist_date = f"{before_date}T18:00:00Z"
                    odds_url = "https://api.the-odds-api.com/v4/historical/sports/baseball_mlb/odds"
                    params = {
                        'apiKey': ODDS_API_KEY,
                        'regions': 'us',
                        'markets': 'totals',
                        'oddsFormat': 'american',
                        'date': hist_date
                    }
                    response = requests.get(odds_url, params=params)
                    games_data = response.json().get('data', [])
                else:
                    odds_url = "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds"
                    params = {
                        'apiKey': ODDS_API_KEY,
                        'regions': 'us',
                        'markets': 'totals',
                        'oddsFormat': 'american'
                    }
                    response = requests.get(odds_url, params=params)
                    games_data = response.json()

                for game in games_data:
                    ht = game.get('home_team', '')
                    at = game.get('away_team', '')
                    if home_team in ht or home_team in at:
                        for bookmaker in game.get('bookmakers', []):
                            for market in bookmaker.get('markets', []):
                                if market['key'] == 'totals':
                                    game_total = market['outcomes'][0]['point']
                                    total_factor = 1 - ((game_total - 8.5) * 0.02)
                                    total_factor = max(0.95, min(1.05, round(total_factor, 3)))
                            break
                        break
            except:
                pass

        base = expected_bf * pitcher_skill
        combined_factor = opp_factor * park_factor * umpire_factor * velo_factor * weather_adj * total_factor
        combined_factor = max(0.90, min(1.10, combined_factor))
        final_projection = round(base * combined_factor, 1)

        return {
            'projection': final_projection,
            'base': round(base, 2),
            'pitcher_hand': pitcher_hand,
            'lineup_k_pct': final_opp_k_pct,
            'pitcher_skill': pitcher_skill,
            'expected_bf': expected_bf,
            'expected_innings': expected_innings,
            'expected_pitch_count': expected_pitch_count,
            'umpire_name': umpire_name,
            'umpire_factor': umpire_factor,
            'opp_factor': opp_factor,
            'park_factor': park_factor,
            'velo_factor': velo_factor,
            'total_factor': total_factor,
            'combined_factor': round(combined_factor, 3),
            'season_k_pct': season_k_pct,
            'last5_k': round(df['strikeouts'].head(5).mean(), 2),
            'last10_k': round(df['strikeouts'].head(10).mean(), 2),
            'last10_k_avg': last10_k_avg,
            'last10_k_std': last10_k_std,
            'cv': cv,
            'confidence_tier': confidence_tier,
            'season_avg_ip': season_avg_ip,
            'pitches_per_inning': pitches_per_inning,
            'last3_pitches': last3_pitches,
            'season_avg_pitches': season_avg_pitches,
            'pitch_count_factor': round(pitch_based_ip, 2),
            'lineup_factor': round(lineup_k_pct, 3) if lineup_k_pct else None,
            'game_log': df[['date', 'opponent', 'strikeouts', 'innings', 'batters_faced', 'pitches']].head(10).to_dict('records')
        }

    except Exception as e:
        return None

# ---- NBA POINTS PROJECTION ENGINE ----
def run_nba_points_projection(player_name, opponent_abbrev, home_team, away_team, home_or_away, season='2025-26'):
    try:
        player_list = nba_players.find_players_by_full_name(player_name)
        if not player_list:
            return None
        player_id = player_list[0]['id']

        logs = playergamelog.PlayerGameLog(player_id=player_id, season=season)
        df = logs.get_data_frames()[0]
        if df.empty or len(df) < 5:
            return None

        df = df[['GAME_DATE', 'MATCHUP', 'PTS', 'FGA', 'FGM', 'FG3M', 'FTA', 'FTM', 'FG_PCT', 'MIN']]
        df['MIN'] = pd.to_numeric(df['MIN'], errors='coerce')
        df['FGA'] = pd.to_numeric(df['FGA'], errors='coerce')
        df = df.iloc[::-1].reset_index(drop=True)

        season_ppg = round(df['PTS'].mean(), 1)
        season_mpg = round(df['MIN'].mean(), 1)
        season_fga = round(df['FGA'].mean(), 1)
        last5_avg = round(df['PTS'].tail(5).mean(), 1)
        last10_avg = round(df['PTS'].tail(10).mean(), 1)
        last5_fga = round(df['FGA'].tail(5).mean(), 1)
        last5_min = round(df['MIN'].tail(5).mean(), 1)
        last10_min = round(df['MIN'].tail(10).mean(), 1)

        last10_pts = df['PTS'].tail(10)
        last10_pts_avg = round(last10_pts.mean(), 2)
        last10_pts_std = round(last10_pts.std(), 2) if len(last10_pts) > 1 else 0.0
        cv = round(last10_pts_std / last10_pts_avg, 3) if last10_pts_avg > 0 else 1.0

        if cv < 0.20:
            confidence_tier = "🟢 Elite Stability"
        elif cv < 0.35:
            confidence_tier = "🟡 Normal"
        elif cv < 0.50:
            confidence_tier = "🟠 High Variance"
        else:
            confidence_tier = "🔴 Pass Candidate"

        base = (last5_avg * 0.40) + (last10_avg * 0.30) + (season_ppg * 0.30)

        fga_factor = round(last5_fga / season_fga, 3) if season_fga > 0 else 1.0
        fga_factor = max(0.95, min(1.05, fga_factor))

        adv_stats = leaguedashplayerstats.LeagueDashPlayerStats(
            season=season,
            per_mode_detailed='PerGame',
            measure_type_detailed_defense='Advanced'
        )
        adv_df = adv_stats.get_data_frames()[0]
        player_adv = adv_df[adv_df['PLAYER_ID'] == player_id]
        usage_rate = round(float(player_adv['USG_PCT'].iloc[0]), 3) if not player_adv.empty else 0.20

        team_stats = leaguedashteamstats.LeagueDashTeamStats(
            season=season,
            per_mode_detailed='PerGame',
            measure_type_detailed_defense='Advanced'
        )
        teams_df = team_stats.get_data_frames()[0]
        opp_full_name = nba_abbrev_to_name.get(opponent_abbrev, '')
        opp_team = teams_df[teams_df['TEAM_NAME'] == opp_full_name]
        opp_def_rating = round(float(opp_team['DEF_RATING'].iloc[0]), 1) if not opp_team.empty else league_avg_def_rating
        opp_pace = round(float(opp_team['PACE'].iloc[0]), 1) if not opp_team.empty else league_avg_pace

        home_games = df[df['MATCHUP'].str.contains('vs.')]
        away_games = df[df['MATCHUP'].str.contains('@')]
        home_ppg = round(home_games['PTS'].mean(), 1) if not home_games.empty else season_ppg
        away_ppg = round(away_games['PTS'].mean(), 1) if not away_games.empty else season_ppg
        raw_location_adj = round(home_ppg - season_ppg, 2) if home_or_away == 'home' else round(away_ppg - season_ppg, 2)
        location_adj = max(-2.0, min(2.0, raw_location_adj))

        expected_minutes = round(
            (season_mpg * 0.30) + (last10_min * 0.30) + (last5_min * 0.40), 1
        )

        df['GAME_DATE'] = pd.to_datetime(df['GAME_DATE'])
        most_recent_game = df['GAME_DATE'].iloc[-1]
        days_rest = (datetime.today() - most_recent_game).days
        if days_rest == 0:
            rest_adj = -1.5
        elif days_rest >= 3:
            rest_adj = 1.0
        else:
            rest_adj = 0

        game_total = None
        spread = None
        try:
            odds_url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
            params = {'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': 'totals,spreads', 'oddsFormat': 'american'}
            response = requests.get(odds_url, params=params)
            games_data = response.json()
            for game in games_data:
                ht = game.get('home_team', '')
                at = game.get('away_team', '')
                if home_team in ht or home_team in at:
                    for bookmaker in game.get('bookmakers', []):
                        for market in bookmaker.get('markets', []):
                            if market['key'] == 'totals':
                                game_total = market['outcomes'][0]['point']
                            if market['key'] == 'spreads':
                                for outcome in market['outcomes']:
                                    if home_team in outcome['name']:
                                        spread = outcome['point']
                        break
                    break
        except:
            pass

        team_total_adj = 0
        blowout_minutes_adj = 0
        implied_team_total = None

        if game_total and spread:
            if home_or_away == 'home':
                implied_team_total = round((game_total / 2) + (abs(spread) / 2 * (1 if spread < 0 else -1)), 1)
            else:
                implied_team_total = round((game_total / 2) - (abs(spread) / 2 * (1 if spread < 0 else -1)), 1)
            team_total_adj = round((implied_team_total - league_avg_team_score) * 0.08, 2)
            if abs(spread) >= 12:
                blowout_minutes_adj = -4
            elif abs(spread) >= 9:
                blowout_minutes_adj = -2

        final_expected_minutes = round(expected_minutes + blowout_minutes_adj, 1)
        pts_per_minute = round(season_ppg / season_mpg, 3) if season_mpg > 0 else 0
        minutes_pts_adj = round((final_expected_minutes - season_mpg) * pts_per_minute, 2)

        usage_adj = round((usage_rate - 0.20) * 10, 2)
        def_adj = round((opp_def_rating - league_avg_def_rating) * 0.2, 2)
        pace_adj = round((opp_pace - league_avg_pace) * 0.25, 2)

        raw_adjustment = (usage_adj + def_adj + pace_adj + team_total_adj + location_adj + rest_adj + minutes_pts_adj)
        raw_adjustment = max(-6.0, min(6.0, raw_adjustment))

        final_projection = round((base + raw_adjustment) * fga_factor, 1)

        return {
            'projection': final_projection,
            'base': round(base, 2),
            'season_ppg': season_ppg,
            'last5_avg': last5_avg,
            'last10_avg': last10_avg,
            'season_mpg': season_mpg,
            'expected_minutes': final_expected_minutes,
            'usage_rate': usage_rate,
            'fga_factor': fga_factor,
            'opp_def_rating': opp_def_rating,
            'opp_pace': opp_pace,
            'location_adj': location_adj,
            'rest_adj': rest_adj,
            'team_total_adj': team_total_adj,
            'minutes_pts_adj': minutes_pts_adj,
            'usage_adj': usage_adj,
            'def_adj': def_adj,
            'pace_adj': pace_adj,
            'implied_team_total': implied_team_total,
            'game_total': game_total,
            'cv': cv,
            'confidence_tier': confidence_tier,
            'days_rest': days_rest
        }

    except Exception as e:
        return None

# ---- NBA ASSISTS PROJECTION ENGINE ----
def run_nba_assists_projection(player_name, opponent_abbrev, home_team, away_team, home_or_away, season='2025-26'):
    try:
        player_list = nba_players.find_players_by_full_name(player_name)
        if not player_list:
            return None
        player_id = player_list[0]['id']

        logs = playergamelog.PlayerGameLog(player_id=player_id, season=season)
        df = logs.get_data_frames()[0]
        if df.empty or len(df) < 5:
            return None

        df = df[['GAME_DATE', 'MATCHUP', 'AST', 'TOV', 'MIN']]
        df['MIN'] = pd.to_numeric(df['MIN'], errors='coerce')
        df['AST'] = pd.to_numeric(df['AST'], errors='coerce')
        df['TOV'] = pd.to_numeric(df['TOV'], errors='coerce')
        df = df.iloc[::-1].reset_index(drop=True)

        season_apg = round(df['AST'].mean(), 1)
        season_mpg = round(df['MIN'].mean(), 1)
        season_tov = round(df['TOV'].mean(), 1)
        last5_avg = round(df['AST'].tail(5).mean(), 1)
        last10_avg = round(df['AST'].tail(10).mean(), 1)
        last5_min = round(df['MIN'].tail(5).mean(), 1)
        last10_min = round(df['MIN'].tail(10).mean(), 1)
        last5_tov = round(df['TOV'].tail(5).mean(), 1)

        last10_ast = df['AST'].tail(10)
        last10_ast_avg = round(last10_ast.mean(), 2)
        last10_ast_std = round(last10_ast.std(), 2) if len(last10_ast) > 1 else 0.0
        cv = round(last10_ast_std / last10_ast_avg, 3) if last10_ast_avg > 0 else 1.0

        if cv < 0.20:
            confidence_tier = "🟢 Elite Stability"
        elif cv < 0.35:
            confidence_tier = "🟡 Normal"
        elif cv < 0.50:
            confidence_tier = "🟠 High Variance"
        else:
            confidence_tier = "🔴 Pass Candidate"

        base = (last5_avg * 0.40) + (last10_avg * 0.30) + (season_apg * 0.30)

        tov_factor = round(last5_tov / season_tov, 3) if season_tov > 0 else 1.0
        tov_factor = max(0.95, min(1.05, tov_factor))

        adv_stats = leaguedashplayerstats.LeagueDashPlayerStats(
            season=season,
            per_mode_detailed='PerGame',
            measure_type_detailed_defense='Advanced'
        )
        adv_df = adv_stats.get_data_frames()[0]
        player_adv = adv_df[adv_df['PLAYER_ID'] == player_id]
        usage_rate = round(float(player_adv['USG_PCT'].iloc[0]), 3) if not player_adv.empty else 0.20
        ast_pct = round(float(player_adv['AST_PCT'].iloc[0]), 3) if not player_adv.empty else 0.15

        potential_assists = None
        potential_ast_adj = 0
        try:
            from nba_api.stats.endpoints import leaguedashptstats
            pt_stats = leaguedashptstats.LeagueDashPtStats(
                season=season,
                per_mode_simple='PerGame',
                player_or_team='Player',
                pt_measure_type='Passing'
            )
            pt_df = pt_stats.get_data_frames()[0]
            player_pt = pt_df[pt_df['PLAYER_ID'] == player_id]
            if not player_pt.empty and 'POTENTIAL_AST' in player_pt.columns:
                potential_assists = round(float(player_pt['POTENTIAL_AST'].iloc[0]), 1)
                if potential_assists and season_apg > 0:
                    expected_ast_from_potential = potential_assists * 0.45
                    potential_ast_adj = round((expected_ast_from_potential - season_apg) * 0.25, 2)
                    potential_ast_adj = max(-0.75, min(0.75, potential_ast_adj))
        except:
            pass

        team_stats = leaguedashteamstats.LeagueDashTeamStats(
            season=season,
            per_mode_detailed='PerGame',
            measure_type_detailed_defense='Advanced'
        )
        teams_df = team_stats.get_data_frames()[0]
        opp_full_name = nba_abbrev_to_name.get(opponent_abbrev, '')
        opp_team = teams_df[teams_df['TEAM_NAME'] == opp_full_name]
        opp_pace = round(float(opp_team['PACE'].iloc[0]), 1) if not opp_team.empty else league_avg_pace

        opp_ast_allowed = 25.0
        try:
            opp_basic = leaguedashteamstats.LeagueDashTeamStats(
                season=season,
                per_mode_detailed='PerGame',
                measure_type_detailed_defense='Base'
            )
            opp_basic_df = opp_basic.get_data_frames()[0]
            opp_basic_row = opp_basic_df[opp_basic_df['TEAM_NAME'] == opp_full_name]
            if not opp_basic_row.empty and 'OPP_AST' in opp_basic_row.columns:
                opp_ast_allowed = round(float(opp_basic_row['OPP_AST'].iloc[0]), 1)
        except:
            pass

        league_avg_ast_allowed = 25.0
        opp_ast_adj = round((opp_ast_allowed - league_avg_ast_allowed) * 0.05, 2)
        opp_ast_adj = max(-0.5, min(0.5, opp_ast_adj))

        home_games = df[df['MATCHUP'].str.contains('vs.')]
        away_games = df[df['MATCHUP'].str.contains('@')]
        home_apg = round(home_games['AST'].mean(), 1) if not home_games.empty else season_apg
        away_apg = round(away_games['AST'].mean(), 1) if not away_games.empty else season_apg
        raw_location_adj = round(home_apg - season_apg, 2) if home_or_away == 'home' else round(away_apg - season_apg, 2)
        location_adj = max(-1.5, min(1.5, raw_location_adj))

        expected_minutes = round(
            (season_mpg * 0.30) + (last10_min * 0.30) + (last5_min * 0.40), 1
        )

        df['GAME_DATE'] = pd.to_datetime(df['GAME_DATE'])
        most_recent_game = df['GAME_DATE'].iloc[-1]
        days_rest = (datetime.today() - most_recent_game).days
        if days_rest == 0:
            rest_adj = -0.5
        elif days_rest >= 3:
            rest_adj = 0.3
        else:
            rest_adj = 0

        game_total = None
        spread = None
        try:
            odds_url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
            params = {'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': 'totals,spreads', 'oddsFormat': 'american'}
            response = requests.get(odds_url, params=params)
            games_data = response.json()
            for game in games_data:
                ht = game.get('home_team', '')
                at = game.get('away_team', '')
                if home_team in ht or home_team in at:
                    for bookmaker in game.get('bookmakers', []):
                        for market in bookmaker.get('markets', []):
                            if market['key'] == 'totals':
                                game_total = market['outcomes'][0]['point']
                            if market['key'] == 'spreads':
                                for outcome in market['outcomes']:
                                    if home_team in outcome['name']:
                                        spread = outcome['point']
                        break
                    break
        except:
            pass

        if game_total:
            total_adj = round((game_total - 225) * 0.015, 2)
            total_adj = max(-0.5, min(0.5, total_adj))
        else:
            total_adj = 0

        blowout_minutes_adj = 0
        if spread and abs(spread) >= 12:
            blowout_minutes_adj = -4
        elif spread and abs(spread) >= 9:
            blowout_minutes_adj = -2

        pace_adj = round((opp_pace - league_avg_pace) * 0.12, 2)

        final_expected_minutes = round(expected_minutes + blowout_minutes_adj, 1)
        ast_per_minute = round(season_apg / season_mpg, 3) if season_mpg > 0 else 0
        minutes_ast_adj = round((final_expected_minutes - season_mpg) * ast_per_minute, 2)

        ast_pct_adj = round((ast_pct - 0.25) * 6, 2)
        ast_pct_adj = max(-1.5, min(1.5, ast_pct_adj))

        raw_adjustment = (
            pace_adj + location_adj + rest_adj +
            minutes_ast_adj + ast_pct_adj + opp_ast_adj +
            total_adj + potential_ast_adj
        )
        raw_adjustment = max(-3.0, min(3.0, raw_adjustment))

        final_projection = max(0, round(base + raw_adjustment, 1))

        return {
            'projection': final_projection,
            'base': round(base, 2),
            'season_apg': season_apg,
            'last5_avg': last5_avg,
            'last10_avg': last10_avg,
            'season_mpg': season_mpg,
            'expected_minutes': final_expected_minutes,
            'blowout_minutes_adj': blowout_minutes_adj,
            'usage_rate': usage_rate,
            'ast_pct': ast_pct,
            'ast_pct_adj': ast_pct_adj,
            'tov_factor': tov_factor,
            'potential_assists': potential_assists,
            'potential_ast_adj': potential_ast_adj,
            'opp_pace': opp_pace,
            'location_adj': location_adj,
            'rest_adj': rest_adj,
            'minutes_ast_adj': minutes_ast_adj,
            'pace_adj': pace_adj,
            'opp_ast_adj': opp_ast_adj,
            'opp_ast_allowed': opp_ast_allowed,
            'total_adj': total_adj,
            'raw_adjustment': round(raw_adjustment, 2),
            'game_total': game_total,
            'spread': spread,
            'cv': cv,
            'confidence_tier': confidence_tier,
            'days_rest': days_rest
        }

    except Exception as e:
        return None

pitchers_list = get_all_pitchers()

# ---- SIDEBAR ----
with st.sidebar:
    st.markdown("""
        <div style='text-align: center; padding: 20px 0 10px 0;'>
            <img src='https://raw.githubusercontent.com/austinwinkler6-ux/mlb_strikeout_model/main/ModelMetricsLogo.png' width='140'/>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    admin_nav = ["🔬 Model Lab", "🧪 Backtest"] if is_admin else []

    nav = st.radio(
        "Navigation",
        ["🏠 Home", "⚾ MLB Models", "🏈 NFL Models", "🏀 NBA Models", "📒 Bet Tracker"] + admin_nav + ["⚙️ Settings"],
        label_visibility="collapsed"
    )

    st.markdown("---")
    st.caption(f"Logged in as {user.email}")
    if st.button("Logout", use_container_width=True):
        sign_out()
        st.rerun()

# ---- HOME PAGE ----
if nav == "🏠 Home":
    st.title("🏠 Welcome to Model Metrics")
    st.markdown("### Sharp Data. Sharp Bets.")
    st.markdown("---")

    col1, col2, col3 = st.columns(3)
    col1.metric("⚾ MLB Strikeouts", "Live", "Model Active")
    col2.metric("🏈 NFL Models", "Coming Soon", "Season Starting")
    col3.metric("🏀 NBA Points", "Live", "Model Active")

    st.markdown("---")
    st.subheader("📌 How to Use Model Metrics")
    st.markdown("""
    1. **Select your sport** from the sidebar to access the available models.
    2. **Load today's props** to view live player prop lines from FanDuel and DraftKings.
    3. **Run projections** to compare our model's projections against the sportsbooks and identify potential value opportunities.
    4. **Track your bets** using the built-in Bet Tracker to monitor your performance, profit, and ROI over time.
    5. **Follow our edge tiers** — historically, larger model edges tend to produce stronger long-term results, helping you make more disciplined betting decisions.
    """)

# ---- MLB PAGE ----
elif nav == "⚾ MLB Models":
    st.title("⚾ MLB Strikeout Model")

    col_load, col_run_all = st.columns(2)

    with col_load:
        if st.button("📋 Load Today's Props", use_container_width=True):
            with st.spinner("Pulling today's props..."):
                try:
                    events_url = "https://api.the-odds-api.com/v4/sports/baseball_mlb/events"
                    events_params = {'apiKey': ODDS_API_KEY, 'dateFormat': 'iso'}
                    events_data = requests.get(events_url, params=events_params).json()
                    all_pitchers = {}

                    for event in events_data:
                        home = event['home_team']
                        away = event['away_team']
                        event_id = event['id']

                        props_url = f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events/{event_id}/odds"
                        props_params = {'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': 'pitcher_strikeouts', 'oddsFormat': 'american'}
                        props_data = requests.get(props_url, params=props_params).json()

                        for bookmaker in props_data.get('bookmakers', []):
                            if bookmaker['key'] in ['fanduel', 'draftkings']:
                                book_name = bookmaker['title']
                                for market in bookmaker.get('markets', []):
                                    if market['key'] == 'pitcher_strikeouts':
                                        for outcome in market['outcomes']:
                                            pitcher = outcome['description']
                                            direction = outcome['name']
                                            line = outcome['point']
                                            odds = outcome['price']

                                            if pitcher not in all_pitchers:
                                                all_pitchers[pitcher] = {
                                                    'home': home, 'away': away,
                                                    'FanDuel Line': None, 'FanDuel Over': None, 'FanDuel Under': None,
                                                    'DraftKings Line': None, 'DraftKings Over': None, 'DraftKings Under': None,
                                                    'Projection': None, 'Edge': None, 'Play': None, 'Tier': None
                                                }

                                            if 'FanDuel' in book_name:
                                                all_pitchers[pitcher]['FanDuel Line'] = line
                                                if direction == 'Over':
                                                    all_pitchers[pitcher]['FanDuel Over'] = odds
                                                else:
                                                    all_pitchers[pitcher]['FanDuel Under'] = odds
                                            elif 'DraftKings' in book_name:
                                                all_pitchers[pitcher]['DraftKings Line'] = line
                                                if direction == 'Over':
                                                    all_pitchers[pitcher]['DraftKings Over'] = odds
                                                else:
                                                    all_pitchers[pitcher]['DraftKings Under'] = odds

                    st.session_state['all_pitchers'] = all_pitchers
                    st.session_state['season'] = '2026'
                except Exception as e:
                    st.error(f"Error: {e}")

    with col_run_all:
        if st.button("🚀 Run All Projections", use_container_width=True):
            if 'all_pitchers' not in st.session_state:
                st.warning("Load today's props first!")
            else:
                all_pitchers = st.session_state['all_pitchers']
                season = st.session_state.get('season', '2026')
                progress_bar = st.progress(0)
                status_text = st.empty()
                total = len(all_pitchers)

                for i, (pitcher, info) in enumerate(all_pitchers.items()):
                    status_text.text(f"Running {i+1} of {total}: {pitcher}")
                    progress_bar.progress((i+1) / total)

                    _, opp, h = get_pitcher_game_info(pitcher)
                    if not opp:
                        opp = info['away']
                        h = info['home']

                    result = run_projection(pitcher, opp, h, season)

                    if result:
                        proj = result['projection']
                        fd_line = info['FanDuel Line']
                        dk_line = info['DraftKings Line']
                        best_line = fd_line or dk_line

                        if best_line:
                            edge = round(proj - best_line, 1)
                            play = "⬆️ OVER" if edge > 0 else "⬇️ UNDER"
                            st.session_state['all_pitchers'][pitcher]['Projection'] = proj
                            st.session_state['all_pitchers'][pitcher]['Edge'] = edge
                            st.session_state['all_pitchers'][pitcher]['Play'] = play
                            st.session_state['all_pitchers'][pitcher]['Tier'] = result['confidence_tier']

                            save_prediction({
                                'date': date.today().strftime('%Y-%m-%d'),
                                'pitcher': pitcher,
                                'opponent': opp,
                                'home_team': h,
                                'projection': proj,
                                'base': result['base'],
                                'book_line': best_line,
                                'edge': edge,
                                'opp_factor': result['opp_factor'],
                                'park_factor': result['park_factor'],
                                'umpire_factor': result['umpire_factor'],
                                'velo_factor': result['velo_factor'],
                                'total_factor': result['total_factor'],
                                'pitch_count_factor': result['pitch_count_factor'],
                                'lineup_factor': result['lineup_factor'],
                                'cv': result['cv'],
                                'confidence_tier': result['confidence_tier'],
                                'actual': None,
                                'sport': 'MLB'
                            })

                status_text.text(f"✅ Done! All {total} projections complete.")
                progress_bar.progress(1.0)
                st.rerun()

    if 'all_pitchers' in st.session_state:
        all_pitchers = st.session_state['all_pitchers']
        season = st.session_state.get('season', '2026')

        sorted_pitchers = sorted(
            all_pitchers.items(),
            key=lambda x: abs(x[1]['Edge']) if x[1]['Edge'] is not None else -1,
            reverse=True
        )

        for pitcher, info in sorted_pitchers:
            col1, col2, col3, col4, col5, col6, col7, col8 = st.columns([2, 1, 1, 1, 1, 1, 1, 1])
            with col1:
                st.write(f"**{pitcher}**")
                st.caption(f"{info['away']} @ {info['home']}")
            with col2:
                st.write(f"FD: {info['FanDuel Line']}")
                st.caption(f"O:{fmt_odds(info['FanDuel Over'])} U:{fmt_odds(info['FanDuel Under'])}")
            with col3:
                st.write(f"DK: {info['DraftKings Line']}")
                st.caption(f"O:{fmt_odds(info['DraftKings Over'])} U:{fmt_odds(info['DraftKings Under'])}")
            with col4:
                st.write(f"Proj: **{info['Projection']}**" if info['Projection'] else "Proj: —")
            with col5:
                st.write(f"Edge: **{info['Edge']}**" if info['Edge'] is not None else "Edge: —")
            with col6:
                st.write(info['Play'] if info['Play'] else "—")
            with col7:
                st.write(info.get('Tier') if info.get('Tier') else "—")
            with col8:
                if st.button("▶️ Run", key=f"run_{pitcher}"):
                    with st.spinner(f"Running {pitcher}..."):
                        _, opp, h = get_pitcher_game_info(pitcher)
                        if not opp:
                            opp = info['away']
                            h = info['home']
                        result = run_projection(pitcher, opp, h, season)
                        if result:
                            proj = result['projection']
                            fd_line = info['FanDuel Line']
                            dk_line = info['DraftKings Line']
                            best_line = fd_line or dk_line
                            if best_line:
                                edge = round(proj - best_line, 1)
                                play = "⬆️ OVER" if edge > 0 else "⬇️ UNDER"
                                st.session_state['all_pitchers'][pitcher]['Projection'] = proj
                                st.session_state['all_pitchers'][pitcher]['Edge'] = edge
                                st.session_state['all_pitchers'][pitcher]['Play'] = play
                                st.session_state['all_pitchers'][pitcher]['Tier'] = result['confidence_tier']
                                st.session_state['last_projection'] = proj
                                st.session_state['last_pitcher'] = pitcher
                                save_prediction({
                                    'date': date.today().strftime('%Y-%m-%d'),
                                    'pitcher': pitcher,
                                    'opponent': opp,
                                    'home_team': h,
                                    'projection': proj,
                                    'base': result['base'],
                                    'book_line': best_line,
                                    'edge': edge,
                                    'opp_factor': result['opp_factor'],
                                    'park_factor': result['park_factor'],
                                    'umpire_factor': result['umpire_factor'],
                                    'velo_factor': result['velo_factor'],
                                    'total_factor': result['total_factor'],
                                    'pitch_count_factor': result['pitch_count_factor'],
                                    'lineup_factor': result['lineup_factor'],
                                    'cv': result['cv'],
                                    'confidence_tier': result['confidence_tier'],
                                    'actual': None,
                                    'sport': 'MLB'
                                })
                                st.rerun()
            st.divider()

# ---- NFL PAGE ----
elif nav == "🏈 NFL Models":
    st.title("🏈 NFL Models")
    st.markdown("---")
    nfl_model = st.selectbox("Select Model", ["NFL Pass Attempts", "NFL Pass Completions", "NFL Receptions"])
    st.markdown("""
        <div style='text-align: center; padding: 80px 0;'>
            <h2>🚧 Coming Soon</h2>
            <p style='color: #64748B; font-size: 18px;'>NFL models are currently in development.<br>Check back when the season starts!</p>
        </div>
    """, unsafe_allow_html=True)

# ---- NBA PAGE ----
elif nav == "🏀 NBA Models":
    st.title("🏀 NBA Models")
    st.markdown("---")

    nba_model_select = st.selectbox("Select Model", ["NBA Points", "NBA Assists"])

    if nba_model_select == "NBA Points":
        col_load, col_run_all = st.columns(2)

        with col_load:
            if st.button("📋 Load Today's NBA Props", use_container_width=True):
                with st.spinner("Pulling today's NBA props..."):
                    try:
                        events_url = "https://api.the-odds-api.com/v4/sports/basketball_nba/events"
                        events_params = {'apiKey': ODDS_API_KEY, 'dateFormat': 'iso'}
                        events_data = requests.get(events_url, params=events_params).json()
                        all_nba_players = {}

                        for event in events_data:
                            home = event['home_team']
                            away = event['away_team']
                            event_id = event['id']

                            props_url = f"https://api.the-odds-api.com/v4/sports/basketball_nba/events/{event_id}/odds"
                            props_params = {'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': 'player_points', 'oddsFormat': 'american'}
                            props_data = requests.get(props_url, params=props_params).json()

                            for bookmaker in props_data.get('bookmakers', []):
                                if bookmaker['key'] in ['fanduel', 'draftkings']:
                                    book_name = bookmaker['title']
                                    for market in bookmaker.get('markets', []):
                                        if market['key'] == 'player_points':
                                            for outcome in market['outcomes']:
                                                player = outcome['description']
                                                direction = outcome['name']
                                                line = outcome['point']
                                                odds = outcome['price']

                                                if player not in all_nba_players:
                                                    all_nba_players[player] = {
                                                        'home': home, 'away': away,
                                                        'FanDuel Line': None, 'FanDuel Over': None, 'FanDuel Under': None,
                                                        'DraftKings Line': None, 'DraftKings Over': None, 'DraftKings Under': None,
                                                        'Projection': None, 'Edge': None, 'Play': None, 'Tier': None
                                                    }

                                                if 'FanDuel' in book_name:
                                                    all_nba_players[player]['FanDuel Line'] = line
                                                    if direction == 'Over':
                                                        all_nba_players[player]['FanDuel Over'] = odds
                                                    else:
                                                        all_nba_players[player]['FanDuel Under'] = odds
                                                elif 'DraftKings' in book_name:
                                                    all_nba_players[player]['DraftKings Line'] = line
                                                    if direction == 'Over':
                                                        all_nba_players[player]['DraftKings Over'] = odds
                                                    else:
                                                        all_nba_players[player]['DraftKings Under'] = odds

                        st.session_state['all_nba_players'] = all_nba_players
                        st.session_state['nba_season'] = '2025-26'
                        st.success(f"Loaded {len(all_nba_players)} players!")
                    except Exception as e:
                        st.error(f"Error: {e}")

        with col_run_all:
            if st.button("🚀 Run All NBA Projections", use_container_width=True):
                if 'all_nba_players' not in st.session_state:
                    st.warning("Load today's NBA props first!")
                else:
                    all_nba_players = st.session_state['all_nba_players']
                    season = st.session_state.get('nba_season', '2025-26')
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    total = len(all_nba_players)

                    for i, (player, info) in enumerate(all_nba_players.items()):
                        status_text.text(f"Running {i+1} of {total}: {player}")
                        progress_bar.progress((i+1) / total)

                        home_team = info['home']
                        away_team = info['away']
                        home_abbrev = nba_name_to_abbrev.get(home_team, '')
                        away_abbrev = nba_name_to_abbrev.get(away_team, '')

                        try:
                            player_list = nba_players.find_players_by_full_name(player)
                            if not player_list:
                                continue
                            player_id = player_list[0]['id']
                            logs = playergamelog.PlayerGameLog(player_id=player_id, season=season)
                            df_check = logs.get_data_frames()[0]
                            if df_check.empty:
                                continue
                            matchup = df_check['MATCHUP'].iloc[0]
                            home_or_away = 'home' if 'vs.' in matchup else 'away'
                            opp_abbrev = away_abbrev if home_or_away == 'home' else home_abbrev
                        except:
                            home_or_away = 'home'
                            opp_abbrev = away_abbrev

                        result = run_nba_points_projection(player, opp_abbrev, home_team, away_team, home_or_away, season)

                        if result:
                            proj = result['projection']
                            fd_line = info['FanDuel Line']
                            dk_line = info['DraftKings Line']
                            best_line = fd_line or dk_line

                            if best_line:
                                edge = round(proj - best_line, 1)
                                play = "⬆️ OVER" if edge > 0 else "⬇️ UNDER"
                                st.session_state['all_nba_players'][player]['Projection'] = proj
                                st.session_state['all_nba_players'][player]['Edge'] = edge
                                st.session_state['all_nba_players'][player]['Play'] = play
                                st.session_state['all_nba_players'][player]['Tier'] = result['confidence_tier']

                                save_prediction({
                                    'date': date.today().strftime('%Y-%m-%d'),
                                    'pitcher': player,
                                    'opponent': opp_abbrev,
                                    'home_team': home_team,
                                    'projection': proj,
                                    'base': result['base'],
                                    'book_line': best_line,
                                    'edge': edge,
                                    'opp_factor': result['def_adj'],
                                    'park_factor': 1.0,
                                    'umpire_factor': 1.0,
                                    'velo_factor': result['fga_factor'],
                                    'total_factor': result['team_total_adj'],
                                    'pitch_count_factor': result['expected_minutes'],
                                    'lineup_factor': result['usage_rate'],
                                    'cv': result['cv'],
                                    'confidence_tier': result['confidence_tier'],
                                    'actual': None,
                                    'sport': 'NBA'
                                })

                    status_text.text(f"✅ Done! All {total} projections complete.")
                    progress_bar.progress(1.0)
                    st.rerun()

        if 'all_nba_players' in st.session_state:
            all_nba_players = st.session_state['all_nba_players']
            season = st.session_state.get('nba_season', '2025-26')

            sorted_players = sorted(
                all_nba_players.items(),
                key=lambda x: abs(x[1]['Edge']) if x[1]['Edge'] is not None else -1,
                reverse=True
            )

            for player, info in sorted_players:
                col1, col2, col3, col4, col5, col6, col7, col8 = st.columns([2, 1, 1, 1, 1, 1, 1, 1])
                with col1:
                    st.write(f"**{player}**")
                    st.caption(f"{info['away']} @ {info['home']}")
                with col2:
                    st.write(f"FD: {info['FanDuel Line']}")
                    st.caption(f"O:{fmt_odds(info['FanDuel Over'])} U:{fmt_odds(info['FanDuel Under'])}")
                with col3:
                    st.write(f"DK: {info['DraftKings Line']}")
                    st.caption(f"O:{fmt_odds(info['DraftKings Over'])} U:{fmt_odds(info['DraftKings Under'])}")
                with col4:
                    st.write(f"Proj: **{info['Projection']}**" if info['Projection'] else "Proj: —")
                with col5:
                    st.write(f"Edge: **{info['Edge']}**" if info['Edge'] is not None else "Edge: —")
                with col6:
                    st.write(info['Play'] if info['Play'] else "—")
                with col7:
                    st.write(info.get('Tier') if info.get('Tier') else "—")
                with col8:
                    if st.button("▶️ Run", key=f"nba_pts_run_{player}"):
                        with st.spinner(f"Running {player}..."):
                            home_team = info['home']
                            away_team = info['away']
                            home_abbrev = nba_name_to_abbrev.get(home_team, '')
                            away_abbrev = nba_name_to_abbrev.get(away_team, '')
                            try:
                                player_list = nba_players.find_players_by_full_name(player)
                                if player_list:
                                    player_id = player_list[0]['id']
                                    logs = playergamelog.PlayerGameLog(player_id=player_id, season=season)
                                    df_check = logs.get_data_frames()[0]
                                    matchup = df_check['MATCHUP'].iloc[0]
                                    home_or_away = 'home' if 'vs.' in matchup else 'away'
                                    opp_abbrev = away_abbrev if home_or_away == 'home' else home_abbrev
                                else:
                                    home_or_away = 'home'
                                    opp_abbrev = away_abbrev
                            except:
                                home_or_away = 'home'
                                opp_abbrev = away_abbrev

                            result = run_nba_points_projection(player, opp_abbrev, home_team, away_team, home_or_away, season)
                            if result:
                                proj = result['projection']
                                fd_line = info['FanDuel Line']
                                dk_line = info['DraftKings Line']
                                best_line = fd_line or dk_line
                                if best_line:
                                    edge = round(proj - best_line, 1)
                                    play = "⬆️ OVER" if edge > 0 else "⬇️ UNDER"
                                    st.session_state['all_nba_players'][player]['Projection'] = proj
                                    st.session_state['all_nba_players'][player]['Edge'] = edge
                                    st.session_state['all_nba_players'][player]['Play'] = play
                                    st.session_state['all_nba_players'][player]['Tier'] = result['confidence_tier']
                                    save_prediction({
                                        'date': date.today().strftime('%Y-%m-%d'),
                                        'pitcher': player,
                                        'opponent': opp_abbrev,
                                        'home_team': home_team,
                                        'projection': proj,
                                        'base': result['base'],
                                        'book_line': best_line,
                                        'edge': edge,
                                        'opp_factor': result['def_adj'],
                                        'park_factor': 1.0,
                                        'umpire_factor': 1.0,
                                        'velo_factor': result['fga_factor'],
                                        'total_factor': result['team_total_adj'],
                                        'pitch_count_factor': result['expected_minutes'],
                                        'lineup_factor': result['usage_rate'],
                                        'cv': result['cv'],
                                        'confidence_tier': result['confidence_tier'],
                                        'actual': None,
                                        'sport': 'NBA'
                                    })
                                    st.rerun()
                st.divider()

    else:  # NBA Assists
        col_load, col_run_all = st.columns(2)

        with col_load:
            if st.button("📋 Load Today's Assist Props", use_container_width=True):
                with st.spinner("Pulling today's assist props..."):
                    try:
                        events_url = "https://api.the-odds-api.com/v4/sports/basketball_nba/events"
                        events_params = {'apiKey': ODDS_API_KEY, 'dateFormat': 'iso'}
                        events_data = requests.get(events_url, params=events_params).json()
                        all_nba_assist_players = {}

                        for event in events_data:
                            home = event['home_team']
                            away = event['away_team']
                            event_id = event['id']

                            props_url = f"https://api.the-odds-api.com/v4/sports/basketball_nba/events/{event_id}/odds"
                            props_params = {'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': 'player_assists', 'oddsFormat': 'american'}
                            props_data = requests.get(props_url, params=props_params).json()

                            for bookmaker in props_data.get('bookmakers', []):
                                if bookmaker['key'] in ['fanduel', 'draftkings']:
                                    book_name = bookmaker['title']
                                    for market in bookmaker.get('markets', []):
                                        if market['key'] == 'player_assists':
                                            for outcome in market['outcomes']:
                                                player = outcome['description']
                                                direction = outcome['name']
                                                line = outcome['point']
                                                odds = outcome['price']

                                                if player not in all_nba_assist_players:
                                                    all_nba_assist_players[player] = {
                                                        'home': home, 'away': away,
                                                        'FanDuel Line': None, 'FanDuel Over': None, 'FanDuel Under': None,
                                                        'DraftKings Line': None, 'DraftKings Over': None, 'DraftKings Under': None,
                                                        'Projection': None, 'Edge': None, 'Play': None, 'Tier': None
                                                    }

                                                if 'FanDuel' in book_name:
                                                    all_nba_assist_players[player]['FanDuel Line'] = line
                                                    if direction == 'Over':
                                                        all_nba_assist_players[player]['FanDuel Over'] = odds
                                                    else:
                                                        all_nba_assist_players[player]['FanDuel Under'] = odds
                                                elif 'DraftKings' in book_name:
                                                    all_nba_assist_players[player]['DraftKings Line'] = line
                                                    if direction == 'Over':
                                                        all_nba_assist_players[player]['DraftKings Over'] = odds
                                                    else:
                                                        all_nba_assist_players[player]['DraftKings Under'] = odds

                        st.session_state['all_nba_assist_players'] = all_nba_assist_players
                        st.session_state['nba_season'] = '2025-26'
                        st.success(f"Loaded {len(all_nba_assist_players)} players!")
                    except Exception as e:
                        st.error(f"Error: {e}")

        with col_run_all:
            if st.button("🚀 Run All Assist Projections", use_container_width=True):
                if 'all_nba_assist_players' not in st.session_state:
                    st.warning("Load today's assist props first!")
                else:
                    all_nba_assist_players = st.session_state['all_nba_assist_players']
                    season = st.session_state.get('nba_season', '2025-26')
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    total = len(all_nba_assist_players)

                    for i, (player, info) in enumerate(all_nba_assist_players.items()):
                        status_text.text(f"Running {i+1} of {total}: {player}")
                        progress_bar.progress((i+1) / total)

                        home_team = info['home']
                        away_team = info['away']
                        home_abbrev = nba_name_to_abbrev.get(home_team, '')
                        away_abbrev = nba_name_to_abbrev.get(away_team, '')

                        try:
                            player_list = nba_players.find_players_by_full_name(player)
                            if not player_list:
                                continue
                            player_id = player_list[0]['id']
                            logs = playergamelog.PlayerGameLog(player_id=player_id, season=season)
                            df_check = logs.get_data_frames()[0]
                            if df_check.empty:
                                continue
                            matchup = df_check['MATCHUP'].iloc[0]
                            home_or_away = 'home' if 'vs.' in matchup else 'away'
                            opp_abbrev = away_abbrev if home_or_away == 'home' else home_abbrev
                        except:
                            home_or_away = 'home'
                            opp_abbrev = away_abbrev

                        result = run_nba_assists_projection(player, opp_abbrev, home_team, away_team, home_or_away, season)

                        if result:
                            proj = result['projection']
                            fd_line = info['FanDuel Line']
                            dk_line = info['DraftKings Line']
                            best_line = fd_line or dk_line

                            if best_line:
                                edge = round(proj - best_line, 1)
                                play = "⬆️ OVER" if edge > 0 else "⬇️ UNDER"
                                st.session_state['all_nba_assist_players'][player]['Projection'] = proj
                                st.session_state['all_nba_assist_players'][player]['Edge'] = edge
                                st.session_state['all_nba_assist_players'][player]['Play'] = play
                                st.session_state['all_nba_assist_players'][player]['Tier'] = result['confidence_tier']

                                save_prediction({
                                    'date': date.today().strftime('%Y-%m-%d'),
                                    'pitcher': player,
                                    'opponent': opp_abbrev,
                                    'home_team': home_team,
                                    'projection': proj,
                                    'base': result['base'],
                                    'book_line': best_line,
                                    'edge': edge,
                                    'opp_factor': result['opp_ast_adj'],
                                    'park_factor': 1.0,
                                    'umpire_factor': 1.0,
                                    'velo_factor': result['ast_pct_adj'],
                                    'total_factor': result['total_adj'],
                                    'pitch_count_factor': result['expected_minutes'],
                                    'lineup_factor': result['potential_ast_adj'],
                                    'cv': result['cv'],
                                    'confidence_tier': result['confidence_tier'],
                                    'actual': None,
                                    'sport': 'NBA_AST'
                                })

                    status_text.text(f"✅ Done! All {total} projections complete.")
                    progress_bar.progress(1.0)
                    st.rerun()

        if 'all_nba_assist_players' in st.session_state:
            all_nba_assist_players = st.session_state['all_nba_assist_players']
            season = st.session_state.get('nba_season', '2025-26')

            sorted_players = sorted(
                all_nba_assist_players.items(),
                key=lambda x: abs(x[1]['Edge']) if x[1]['Edge'] is not None else -1,
                reverse=True
            )

            for player, info in sorted_players:
                col1, col2, col3, col4, col5, col6, col7, col8 = st.columns([2, 1, 1, 1, 1, 1, 1, 1])
                with col1:
                    st.write(f"**{player}**")
                    st.caption(f"{info['away']} @ {info['home']}")
                with col2:
                    st.write(f"FD: {info['FanDuel Line']}")
                    st.caption(f"O:{fmt_odds(info['FanDuel Over'])} U:{fmt_odds(info['FanDuel Under'])}")
                with col3:
                    st.write(f"DK: {info['DraftKings Line']}")
                    st.caption(f"O:{fmt_odds(info['DraftKings Over'])} U:{fmt_odds(info['DraftKings Under'])}")
                with col4:
                    st.write(f"Proj: **{info['Projection']}**" if info['Projection'] else "Proj: —")
                with col5:
                    st.write(f"Edge: **{info['Edge']}**" if info['Edge'] is not None else "Edge: —")
                with col6:
                    st.write(info['Play'] if info['Play'] else "—")
                with col7:
                    st.write(info.get('Tier') if info.get('Tier') else "—")
                with col8:
                    if st.button("▶️ Run", key=f"nba_ast_run_{player}"):
                        with st.spinner(f"Running {player}..."):
                            home_team = info['home']
                            away_team = info['away']
                            home_abbrev = nba_name_to_abbrev.get(home_team, '')
                            away_abbrev = nba_name_to_abbrev.get(away_team, '')
                            try:
                                player_list = nba_players.find_players_by_full_name(player)
                                if player_list:
                                    player_id = player_list[0]['id']
                                    logs = playergamelog.PlayerGameLog(player_id=player_id, season=season)
                                    df_check = logs.get_data_frames()[0]
                                    matchup = df_check['MATCHUP'].iloc[0]
                                    home_or_away = 'home' if 'vs.' in matchup else 'away'
                                    opp_abbrev = away_abbrev if home_or_away == 'home' else home_abbrev
                                else:
                                    home_or_away = 'home'
                                    opp_abbrev = away_abbrev
                            except:
                                home_or_away = 'home'
                                opp_abbrev = away_abbrev

                            result = run_nba_assists_projection(player, opp_abbrev, home_team, away_team, home_or_away, season)
                            if result:
                                proj = result['projection']
                                fd_line = info['FanDuel Line']
                                dk_line = info['DraftKings Line']
                                best_line = fd_line or dk_line
                                if best_line:
                                    edge = round(proj - best_line, 1)
                                    play = "⬆️ OVER" if edge > 0 else "⬇️ UNDER"
                                    st.session_state['all_nba_assist_players'][player]['Projection'] = proj
                                    st.session_state['all_nba_assist_players'][player]['Edge'] = edge
                                    st.session_state['all_nba_assist_players'][player]['Play'] = play
                                    st.session_state['all_nba_assist_players'][player]['Tier'] = result['confidence_tier']
                                    save_prediction({
                                        'date': date.today().strftime('%Y-%m-%d'),
                                        'pitcher': player,
                                        'opponent': opp_abbrev,
                                        'home_team': home_team,
                                        'projection': proj,
                                        'base': result['base'],
                                        'book_line': best_line,
                                        'edge': edge,
                                        'opp_factor': result['opp_ast_adj'],
                                        'park_factor': 1.0,
                                        'umpire_factor': 1.0,
                                        'velo_factor': result['ast_pct_adj'],
                                        'total_factor': result['total_adj'],
                                        'pitch_count_factor': result['expected_minutes'],
                                        'lineup_factor': result['potential_ast_adj'],
                                        'cv': result['cv'],
                                        'confidence_tier': result['confidence_tier'],
                                        'actual': None,
                                        'sport': 'NBA_AST'
                                    })
                                    st.rerun()
                st.divider()

# ---- BET TRACKER PAGE ----
elif nav == "📒 Bet Tracker":
    st.title("📒 Bet Tracker")

    sport_filter = st.selectbox("Filter by Sport", ["All", "MLB", "NBA", "NBA_AST"], key="bet_sport_filter")
    sport_query = None if sport_filter == "All" else sport_filter

    st.markdown("---")
    st.subheader("Log a New Bet")

    bet_sport = st.selectbox("Sport", ["MLB", "NBA", "NBA_AST"], key="new_bet_sport")

    col1, col2, col3 = st.columns(3)
    with col1:
        if bet_sport == "MLB":
            bt_player = st.selectbox("Pitcher", pitchers_list, index=0)
        else:
            bt_player = st.text_input("Player Name", placeholder="e.g. LeBron James")
        bt_projection = st.number_input("Your Projection", value=None, placeholder="e.g. 6.4")
        bt_opening_line = st.number_input("Book Line", value=None, placeholder="e.g. 5.5")
        bt_bet = st.number_input("Bet Amount ($)", value=None, placeholder="e.g. 100")
    with col2:
        bt_date = st.date_input("Date")
        bt_over_under = st.selectbox("Over or Under?", ["Over", "Under"])
        bt_odds = st.number_input("Odds (e.g. -140 or +110)", value=None, placeholder="e.g. -140")
        bt_actual = st.number_input("Actual Result", value=None, placeholder="e.g. 7")
    with col3:
        bt_result = st.selectbox("Result", ["Pending", "Win", "Loss"])

    if st.button("Log Bet"):
        odds_val = bt_odds or -110
        bet_val = bt_bet or 0
        profit = calc_profit(bet_val, odds_val, bt_result)
        save_bet({
            'date': str(bt_date),
            'pitcher': bt_player,
            'projection': bt_projection or 0,
            'opening_line': bt_opening_line or 0,
            'over_under': bt_over_under,
            'odds': odds_val,
            'bet_amount': bet_val,
            'result': bt_result,
            'actual': bt_actual or 0,
            'profit': profit,
            'sport': bet_sport
        })
        st.rerun()

    bets = load_bets(sport_query)

    if bets:
        st.markdown("---")
        st.subheader("📈 Performance Summary")
        bets_df = pd.DataFrame(bets)

        settled = bets_df[bets_df['result'] != 'Pending']

        if not settled.empty:
            wins = len(settled[settled['result'] == 'Win'])
            losses = len(settled[settled['result'] == 'Loss'])
            total = wins + losses
            win_pct = round(wins / total * 100, 1) if total > 0 else 0
            total_profit = round(settled['profit'].sum(), 2)
            total_wagered = round(settled['bet_amount'].sum(), 2)
            roi = round(total_profit / total_wagered * 100, 1) if total_wagered > 0 else 0

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Record", f"{wins}-{losses}")
            col2.metric("Win %", f"{win_pct}%")
            col3.metric("Total Profit", f"${total_profit}")
            col4.metric("ROI", f"{roi}%")

        settled_with_data = bets_df[
            (bets_df['result'] != 'Pending') &
            (bets_df['opening_line'] > 0) &
            (bets_df['projection'] > 0)
        ].copy()

        if not settled_with_data.empty:
            st.markdown("---")
            st.subheader("📊 Edge Tier Win Rate")
            settled_with_data['edge'] = (settled_with_data['projection'] - settled_with_data['opening_line']).abs().round(1)
            settled_with_data['win'] = settled_with_data['result'] == 'Win'

            tiers = [
                ('0.0 to 0.4', 0.0, 0.4),
                ('0.5 to 0.9', 0.5, 0.9),
                ('1.0 to 1.4', 1.0, 1.4),
                ('1.5+', 1.5, 99)
            ]

            tier_data = []
            for label, low, high in tiers:
                for direction in ['⬆️ OVER', '⬇️ UNDER']:
                    dir_df = settled_with_data[settled_with_data['over_under'].str.lower() == direction.split(' ')[1].lower()]
                    tier_df = dir_df[(dir_df['edge'] >= low) & (dir_df['edge'] <= high)]
                    if len(tier_df) > 0:
                        win_rate = round(tier_df['win'].mean() * 100, 1)
                        tier_data.append({
                            'Direction': direction,
                            'Edge Tier': label,
                            'Bets': len(tier_df),
                            'Wins': int(tier_df['win'].sum()),
                            'Win Rate': f"{win_rate}%"
                        })

            if tier_data:
                st.dataframe(pd.DataFrame(tier_data), use_container_width=True)

        st.markdown("---")
        st.subheader("📝 All Bets")

        display_df = bets_df.drop(columns=['id', 'created_at', 'user_id'], errors='ignore')

        edited_df = st.data_editor(
            display_df,
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                'result': st.column_config.SelectboxColumn('Result', options=['Pending', 'Win', 'Loss']),
                'actual': st.column_config.NumberColumn('Actual', min_value=0),
                'opening_line': st.column_config.NumberColumn('Book Line', min_value=0.0, step=0.5),
                'projection': st.column_config.NumberColumn('Projection', min_value=0.0, step=0.1),
                'bet_amount': st.column_config.NumberColumn('Bet ($)', min_value=0.0),
                'odds': st.column_config.NumberColumn('Odds'),
                'profit': st.column_config.NumberColumn('Profit ($)'),
                'over_under': st.column_config.SelectboxColumn('O/U', options=['Over', 'Under']),
                'sport': st.column_config.SelectboxColumn('Sport', options=['MLB', 'NBA', 'NBA_AST', 'NFL']),
            }
        )

        col_save, col_clear = st.columns(2)
        with col_save:
            if st.button("💾 Save Table Changes", use_container_width=True):
                updated_bets = edited_df.to_dict('records')
                for i, b in enumerate(updated_bets):
                    b['profit'] = calc_profit(b.get('bet_amount', 0), b.get('odds', -110), b.get('result', 'Pending'))
                    if i < len(bets) and bets[i].get('id'):
                        update_bet(bets[i]['id'], {
                            'actual': b.get('actual'),
                            'result': b.get('result'),
                            'odds': b.get('odds'),
                            'bet_amount': b.get('bet_amount'),
                            'opening_line': b.get('opening_line'),
                            'projection': b.get('projection'),
                            'over_under': b.get('over_under'),
                            'profit': b['profit'],
                            'sport': b.get('sport', 'MLB')
                        })
                st.rerun()
        with col_clear:
            if st.button("🗑️ Clear All Bets", use_container_width=True):
                for bet in bets:
                    delete_bet(bet['id'])
                st.rerun()

# ---- MODEL LAB (ADMIN ONLY) ----
elif nav == "🔬 Model Lab" and is_admin:
    st.title("🔬 Model Lab")

    lab_sport = st.selectbox("Sport", ["MLB", "NBA Points", "NBA Assists"], key="lab_sport")

    sport_key = 'MLB' if lab_sport == 'MLB' else ('NBA' if lab_sport == 'NBA Points' else 'NBA_AST')
    preds = load_predictions(sport_key)
    preds_with_actual = [p for p in preds if p.get('actual') is not None]

    st.subheader("📥 Update Actual Results")
    today_str = date.today().strftime('%Y-%m-%d')
    preds_today = [p for p in preds if p.get('date') == today_str and p.get('actual') is None]

    if preds_today:
        for i, pred in enumerate(preds_today):
            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                st.write(f"**{pred['pitcher']}** — Proj: {pred['projection']}")
            with col2:
                actual = st.number_input("Actual", value=0, key=f"actual_{i}", min_value=0)
            with col3:
                if st.button("Save", key=f"save_actual_{i}"):
                    update_prediction(pred['id'], {'actual': actual})
                    st.rerun()
    else:
        st.info("No pending predictions for today!")

    st.markdown("---")

    if len(preds_with_actual) < 5:
        st.warning(f"Need at least 5 completed predictions. You have {len(preds_with_actual)} so far.")
    else:
        if lab_sport == "MLB":
            st.subheader("🏆 Model Version Comparison")
            model_versions = {
                'A — Base Only': {'use_park': False, 'use_umpire': False, 'use_pitch_count': False, 'use_total': False, 'desc': 'Pitcher skill × BF only'},
                'B — + Opponent K%': {'use_park': False, 'use_umpire': False, 'use_pitch_count': False, 'use_total': False, 'desc': 'Base + opponent K%'},
                'C — + Park': {'use_park': True, 'use_umpire': False, 'use_pitch_count': False, 'use_total': False, 'desc': 'Base + opp K% + park'},
                'D — + Umpire': {'use_park': True, 'use_umpire': True, 'use_pitch_count': False, 'use_total': False, 'desc': 'Base + opp K% + park + umpire'},
                'E — + Pitch Count': {'use_park': True, 'use_umpire': True, 'use_pitch_count': True, 'use_total': False, 'desc': 'All except total'},
                'F — Full Model': {'use_park': True, 'use_umpire': True, 'use_pitch_count': True, 'use_total': True, 'desc': 'Everything'},
            }

            version_results = []
            for version_name, config in model_versions.items():
                errors = []
                for pred in preds_with_actual:
                    actual = pred['actual']
                    base = pred['base']
                    opp_f = pred['opp_factor']
                    park_f = pred['park_factor'] if config['use_park'] else 1.0
                    ump_f = pred['umpire_factor'] if config['use_umpire'] else 1.0
                    velo_f = pred['velo_factor']
                    total_f = pred['total_factor'] if config['use_total'] else 1.0
                    combined = max(0.90, min(1.10, opp_f * park_f * ump_f * velo_f * total_f))
                    proj = round(base * combined, 1)
                    errors.append(abs(proj - actual))
                mae = round(sum(errors) / len(errors), 2)
                version_results.append({'Version': version_name, 'Description': config['desc'], 'MAE': mae, 'Predictions': len(errors)})

            version_df = pd.DataFrame(version_results).sort_values('MAE')
            best_mae = version_df['MAE'].min()
            version_df['vs Best'] = version_df['MAE'].apply(lambda x: f"+{round(x - best_mae, 2)}" if x > best_mae else "✅ Best")
            st.dataframe(version_df, use_container_width=True)
            st.bar_chart(version_df.set_index('Version')['MAE'])

        elif lab_sport == "NBA Points":
            st.subheader("🏀 NBA Points Model Performance")

        else:
            st.subheader("🏀 NBA Assists — Conversion Rate Tester")
            conversion_rate = st.select_slider(
                "Potential Assist Conversion Rate",
                options=[0.42, 0.45, 0.48],
                value=0.45
            )
            st.caption(f"Testing: expected assists = potential assists × {conversion_rate}")

            if preds_with_actual:
                errors_by_rate = {}
                for rate in [0.42, 0.45, 0.48]:
                    errors = []
                    for pred in preds_with_actual:
                        proj = pred['projection']
                        actual = pred['actual']
                        errors.append(abs(proj - actual))
                    errors_by_rate[rate] = round(sum(errors) / len(errors), 2)

                rate_df = pd.DataFrame([
                    {'Conversion Rate': k, 'MAE': v}
                    for k, v in errors_by_rate.items()
                ])
                st.dataframe(rate_df, use_container_width=True)
                best_rate = min(errors_by_rate, key=errors_by_rate.get)
                st.success(f"✅ Best conversion rate so far: **{best_rate}** with MAE of **{errors_by_rate[best_rate]}**")

        preds_with_tier = [p for p in preds_with_actual if p.get('confidence_tier')]
        if preds_with_tier:
            st.markdown("---")
            st.subheader("🎯 MAE by Confidence Tier")
            tier_df = pd.DataFrame(preds_with_tier)
            tier_df['error'] = (tier_df['projection'] - tier_df['actual']).abs()
            tier_summary = tier_df.groupby('confidence_tier').agg(
                Predictions=('error', 'count'),
                MAE=('error', 'mean')
            ).reset_index()
            tier_summary['MAE'] = tier_summary['MAE'].round(2)
            st.dataframe(tier_summary, use_container_width=True)

        st.markdown("---")
        st.subheader("📋 All Predictions")
        full_df = pd.DataFrame(preds_with_actual)
        full_df['error'] = (full_df['projection'] - full_df['actual']).abs().round(2)
        display_cols = ['date', 'pitcher', 'projection', 'actual', 'error', 'book_line', 'edge']
        if 'confidence_tier' in full_df.columns:
            display_cols.append('confidence_tier')
        st.dataframe(full_df[display_cols].sort_values('date', ascending=False), use_container_width=True)

        col1, col2, col3 = st.columns(3)
        col1.metric("Overall MAE", f"{round(full_df['error'].mean(), 2)}")
        col2.metric("Total Predictions", len(full_df))
        col3.metric("Best Prediction", f"{full_df['error'].min()} error")

# ---- BACKTEST (ADMIN ONLY) ----
elif nav == "🧪 Backtest" and is_admin:
    st.title("🧪 Backtest")

    backtest_sport = st.selectbox("Sport", ["MLB Strikeouts", "NBA Points", "NBA Assists"], key="backtest_sport")
    backtest_date = st.date_input("Select a past date", value=date.today() - timedelta(days=7))

    if backtest_sport == "MLB Strikeouts":
        backtest_season = st.selectbox("Season", ["2026", "2025", "2024"], key="backtest_season")

        if st.button("🔍 Load Games & Run Projections", use_container_width=True):
            with st.spinner(f"Pulling starters for {backtest_date}..."):
                date_str = backtest_date.strftime('%Y-%m-%d')
                starters = get_starters_for_date(date_str)

                if not starters:
                    st.error("No games found for that date")
                else:
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    results = []

                    for i, starter in enumerate(starters):
                        status_text.text(f"Running {starter['pitcher']} ({i+1} of {len(starters)})")
                        progress_bar.progress((i+1) / len(starters))

                        result = run_projection(
                            starter['pitcher'], starter['opponent'], starter['home_team'],
                            backtest_season, before_date=date_str
                        )
                        actual_k = get_actual_strikeouts(starter['game_pk'], starter['pitcher'])

                        if result and actual_k is not None:
                            error = round(abs(result['projection'] - actual_k), 1)
                            results.append({
                                'Pitcher': starter['pitcher'],
                                'Matchup': f"{starter['opponent']} @ {starter['home_team']}",
                                'Projection': result['projection'],
                                'Actual K': actual_k,
                                'Error': error,
                                'Tier': result['confidence_tier']
                            })

                    st.session_state['backtest_results'] = results
                    st.session_state['backtest_date'] = date_str
                    status_text.text(f"✅ Done! {len(results)} pitchers projected.")
                    progress_bar.progress(1.0)

    else:
        backtest_season_nba = st.selectbox("Season", ["2025-26", "2024-25", "2023-24"], key="backtest_season_nba")
        is_assists = backtest_sport == "NBA Assists"

        if st.button("🔍 Load NBA Games & Run Projections", use_container_width=True):
            with st.spinner(f"Pulling NBA games for {backtest_date}..."):
                date_str = backtest_date.strftime('%m/%d/%Y')
                games = get_nba_games_for_date(date_str)

                if not games:
                    st.error("No NBA games found for that date")
                else:
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    results = []
                    total = len(games)

                    for i, game in enumerate(games):
                        status_text.text(f"Processing game {i+1} of {total}")
                        progress_bar.progress((i+1) / total)

                        home_abbrev = game.get('home_team_abbrev', '')
                        away_abbrev = game.get('away_team_abbrev', '')
                        home_name = nba_abbrev_to_name.get(home_abbrev, '')
                        away_name = nba_abbrev_to_name.get(away_abbrev, '')

                        try:
                            box_url = f"https://stats.nba.com/stats/boxscoretraditionalv2?GameID={game['game_id']}&StartPeriod=0&EndPeriod=10&StartRange=0&EndRange=28800&RangeType=0"
                            headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.nba.com'}
                            box_response = requests.get(box_url, headers=headers)
                            box_data = box_response.json()
                            player_stats = box_data['resultSets'][0]
                            headers_list = player_stats['headers']
                            rows = player_stats['rowSet']

                            for row in rows:
                                player = dict(zip(headers_list, row))
                                player_name = player['PLAYER_NAME']
                                actual_val = player.get('AST' if is_assists else 'PTS', None)
                                if actual_val is None:
                                    continue

                                team_abbrev = player.get('TEAM_ABBREVIATION', '')
                                home_or_away = 'home' if team_abbrev == home_abbrev else 'away'
                                opp_abbrev = away_abbrev if home_or_away == 'home' else home_abbrev

                                if is_assists:
                                    result = run_nba_assists_projection(
                                        player_name, opp_abbrev, home_name, away_name,
                                        home_or_away, backtest_season_nba
                                    )
                                else:
                                    result = run_nba_points_projection(
                                        player_name, opp_abbrev, home_name, away_name,
                                        home_or_away, backtest_season_nba
                                    )

                                if result:
                                    error = round(abs(result['projection'] - actual_val), 1)
                                    results.append({
                                        'Player': player_name,
                                        'Matchup': f"{away_name} @ {home_name}",
                                        'Projection': result['projection'],
                                        'Actual': actual_val,
                                        'Error': error,
                                        'Tier': result['confidence_tier']
                                    })
                        except:
                            continue

                    st.session_state['backtest_results'] = results
                    st.session_state['backtest_date'] = backtest_date.strftime('%Y-%m-%d')
                    status_text.text(f"✅ Done! {len(results)} players projected.")
                    progress_bar.progress(1.0)

    if 'backtest_results' in st.session_state and st.session_state['backtest_results']:
        st.markdown("---")
        st.subheader(f"📋 Results for {st.session_state.get('backtest_date', '')}")

        results_df = pd.DataFrame(st.session_state['backtest_results'])
        st.dataframe(results_df.sort_values('Error'), use_container_width=True)

        st.markdown("---")
        col1, col2, col3 = st.columns(3)
        col1.metric("Avg Error (MAE)", f"{round(results_df['Error'].mean(), 2)}")
        col2.metric("Best Projection", f"{results_df['Error'].min()} error")
        col3.metric("Worst Projection", f"{results_df['Error'].max()} error")

        if 'Tier' in results_df.columns:
            st.markdown("---")
            st.subheader("🎯 MAE by Confidence Tier")
            tier_summary = results_df.groupby('Tier').agg(
                Predictions=('Error', 'count'),
                MAE=('Error', 'mean')
            ).reset_index()
            tier_summary['MAE'] = tier_summary['MAE'].round(2)
            st.dataframe(tier_summary, use_container_width=True)

# ---- SETTINGS PAGE ----
elif nav == "⚙️ Settings":
    st.title("⚙️ Settings")
    st.markdown("---")

    st.subheader("Account Information")
    st.write(f"**Email:** {user.email}")
    st.write(f"**Account Type:** {'Admin' if is_admin else 'Standard'}")

    st.markdown("---")
    st.subheader("Subscription")
    st.info("💳 Subscription management coming soon — stay tuned!")

    st.markdown("---")
    st.subheader("Danger Zone")
    if st.button("🚪 Logout", use_container_width=True):
        sign_out()
        st.rerun()
