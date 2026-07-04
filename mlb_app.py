import streamlit as st
import requests
import pandas as pd
from datetime import date, timedelta, datetime
from io import StringIO
from supabase import create_client, Client
from nba_api.stats.endpoints import playergamelog, leaguedashplayerstats, leaguedashteamstats
from nba_api.stats.static import players as nba_players
from scipy import stats

st.set_page_config(page_title="Model Metrics", page_icon="⚾", layout="wide")

ODDS_API_KEY = st.secrets["ODDS_API_KEY"]
ADMIN_EMAIL = "austinwinkler6@icloud.com"

# ---- EV CALCULATOR ----
EDGE_THRESHOLDS = {
    "mlb_strikeouts": 0.75,
    "nba_assists": 0.75,
    "nba_points": 1.5,
    "nfl_pass_attempts": 2.0,
    "nfl_completions": 1.5,
    "nfl_receptions": 1.0,
}

EDGE_SCORE_CAPS = {
    "mlb_strikeouts": 2.0,
    "nba_assists": 2.0,
    "nba_points": 5.0,
    "nfl_pass_attempts": 8.0,
    "nfl_completions": 5.0,
    "nfl_receptions": 2.5,
}

def get_min_std_dev(cv, projection, sport='mlb_strikeouts'):
    if sport == 'mlb_strikeouts':
        if cv >= 0.50:
            return max(2.5, projection * 0.35)
        elif cv >= 0.35:
            return max(2.0, projection * 0.28)
        elif cv >= 0.20:
            return max(1.2, projection * 0.18)
        else:
            return max(0.6, projection * 0.10)
    elif sport == 'nba_points':
        if cv >= 0.50:
            return max(8.0, projection * 0.32)
        elif cv >= 0.35:
            return max(6.0, projection * 0.25)
        elif cv >= 0.20:
            return max(4.0, projection * 0.18)
        else:
            return max(2.5, projection * 0.12)
    elif sport == 'nba_assists':
        if cv >= 0.50:
            return max(3.0, projection * 0.35)
        elif cv >= 0.35:
            return max(2.0, projection * 0.28)
        elif cv >= 0.20:
            return max(1.2, projection * 0.20)
        else:
            return max(0.5, projection * 0.12)
    return max(1.0, projection * 0.20)

def remove_vig(over_odds, under_odds):
    def to_prob(odds):
        if odds > 0:
            return 100 / (odds + 100)
        else:
            return abs(odds) / (abs(odds) + 100)
    over_prob = to_prob(over_odds)
    under_prob = to_prob(under_odds)
    total = over_prob + under_prob
    return round(over_prob / total, 3), round(under_prob / total, 3)

def projection_to_probability(projection, line, std_dev, direction='over'):
    if std_dev <= 0:
        return 0.5
    z_score = (line - projection) / std_dev
    if direction == 'over':
        return round(1 - stats.norm.cdf(z_score), 3)
    else:
        return round(stats.norm.cdf(z_score), 3)

def calculate_ev(model_prob, odds, bet_amount=100):
    if odds > 0:
        profit = (odds / 100) * bet_amount
    else:
        profit = (100 / abs(odds)) * bet_amount
    return round((model_prob * profit) - ((1 - model_prob) * bet_amount), 2)

def calculate_ev_pct(model_prob, odds, bet_amount=100):
    return round((calculate_ev(model_prob, odds, bet_amount) / bet_amount) * 100, 2)

def calculate_score(model_edge, ev_pct, cv, sport="mlb_strikeouts"):
    cap = EDGE_SCORE_CAPS.get(sport, 2.0)
    edge_score = min(40, round((max(0, model_edge) / cap) * 40, 1))
    ev_score = min(35, round((max(0, ev_pct) / 15.0) * 35, 1))
    confidence_score = round(max(0, (0.50 - cv) / 0.50) * 15, 1)
    direction_score = 10 if (model_edge > 0 and ev_pct > 0) else 0
    return max(0, min(100, round(edge_score + ev_score + confidence_score + direction_score)))

def score_to_stars(score):
    if score >= 90: return "⭐⭐⭐⭐⭐"
    elif score >= 75: return "⭐⭐⭐⭐"
    elif score >= 60: return "⭐⭐⭐"
    elif score >= 45: return "⭐⭐"
    else: return "⭐"

def get_tier(model_edge, ev_pct, sport="mlb_strikeouts"):
    threshold = EDGE_THRESHOLDS.get(sport, 0.75)
    model_strong = model_edge >= threshold
    ev_strong = ev_pct >= 4.0
    same_direction = model_edge > 0 and ev_pct > 0
    if model_strong and ev_strong and same_direction:
        return "🥇 Consensus Gold"
    elif model_strong and same_direction:
        return "📊 Model Edge"
    elif ev_strong and same_direction:
        return "💰 +EV Only"
    else:
        return "⚪ Low Signal"

def analyze_prop(projection, line, std_dev, cv, over_odds, under_odds, direction='over', sport='mlb_strikeouts'):
    if not over_odds or not under_odds:
        return None
    try:
        min_std = get_min_std_dev(cv, projection, sport)
        effective_std = max(std_dev, min_std)

        fair_over_prob, fair_under_prob = remove_vig(over_odds, under_odds)
        fair_prob = fair_over_prob if direction == 'over' else fair_under_prob
        model_prob = projection_to_probability(projection, line, effective_std, direction)
        odds = over_odds if direction == 'over' else under_odds
        ev_dollar = calculate_ev(model_prob, odds)
        ev_pct = calculate_ev_pct(model_prob, odds)
        prob_edge = round((model_prob - fair_prob) * 100, 2)
        model_edge = round(projection - line, 2) if direction == 'over' else round(line - projection, 2)
        score = calculate_score(model_edge, ev_pct, cv, sport)
        return {
            'model_prob': model_prob,
            'no_vig_prob': round(fair_prob, 3),
            'prob_edge': prob_edge,
            'ev_dollar': ev_dollar,
            'ev_pct': ev_pct,
            'model_edge': model_edge,
            'score': score,
            'stars': score_to_stars(score),
            'tier': get_tier(model_edge, ev_pct, sport),
            'effective_std': round(effective_std, 2)
        }
    except:
        return None

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
            <p style='color: #64748B; margin-top: 8px;'>Projections • +EV • Confidence Scores</p>
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
        return query.order("created_at", desc=True).execute().data or []
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
        return query.order("created_at", desc=True).execute().data or []
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
        data = requests.get(url).json()
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
        data = requests.get(url).json()
        for side in ['home', 'away']:
            for pid in data['teams'][side]['pitchers']:
                player = data['teams'][side]['players'].get(f'ID{pid}', {})
                name = player.get('person', {}).get('fullName', '')
                if name.lower() == pitcher_name.lower():
                    return player.get('stats', {}).get('pitching', {}).get('strikeOuts', None)
    except:
        pass
    return None

# ---- GET NBA GAMES FOR A DATE ----
def get_nba_games_for_date(game_date_str):
    try:
        url = f"https://stats.nba.com/stats/scoreboardV2?DayOffset=0&LeagueID=00&gameDate={game_date_str}"
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.nba.com'}
        data = requests.get(url, headers=headers).json()
        games = []
        game_header = data['resultSets'][0]
        headers_list = game_header['headers']
        for row in game_header['rowSet']:
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

        season_stat = requests.get(f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season&group=pitching&season={season}&sportId=1").json()['stats'][0]['splits'][0]['stat']

        season_k = int(season_stat['strikeOuts'])
        season_bf = int(season_stat['battersFaced'])
        season_k_pct = round(season_k / season_bf, 3)
        season_pitches_total = int(season_stat.get('numberOfPitches', 0))
        season_strikes = int(season_stat.get('strikes', 0))
        season_strike_pct = round(season_strikes / season_pitches_total, 3) if season_pitches_total > 0 else 0.65

        splits = requests.get(f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=gameLog&group=pitching&season={season}&sportId=1").json()['stats'][0]['splits']

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
                'date': game_date, 'opponent': game['opponent']['name'],
                'strikeouts': int(g['strikeOuts']), 'innings': ip,
                'batters_faced': int(g['battersFaced']), 'pitches': pitches,
                'strike_pct': round(strikes / pitches, 3) if pitches > 0 else 0.65,
                'pitches_per_inning': round(pitches / ip, 2) if ip > 0 else 17.0
            })

        if len(games) < 3:
            return None

        df = pd.DataFrame(games).iloc[::-1].reset_index(drop=True)

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

        if cv < 0.20: confidence_tier = "🟢 Elite Stability"
        elif cv < 0.35: confidence_tier = "🟡 Normal"
        elif cv < 0.50: confidence_tier = "🟠 High Variance"
        else: confidence_tier = "🔴 Pass Candidate"

        last3_pitches = round(df['pitches'].head(3).mean(), 1)
        last10_pitches = round(df['pitches'].head(10).mean(), 1)
        season_avg_pitches = round(df['pitches'].mean(), 1)
        career_high_pitches = df['pitches'].max()
        pitches_per_inning = round(df['pitches_per_inning'].head(10).mean(), 2)

        if use_pitch_count:
            expected_pitch_count = round((season_avg_pitches * 0.30) + (last10_pitches * 0.30) + (last3_pitches * 0.40), 1)
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

        pitcher_skill = round((season_k_pct * 0.70) + (last10_k_pct * 0.15) + (last5_k_pct * 0.15), 3)
        last3_starter = (last3_avg_ip >= 4.8) or (sum(df['innings'].head(3) >= 5.0) >= 2)

        if last3_starter:
            ip_season_w, ip_last10_w, ip_last5_w = 0.20, 0.30, 0.50
        elif last5_avg_ip > season_avg_ip * 1.5 or last5_avg_ip < season_avg_ip * 0.6:
            ip_season_w, ip_last10_w, ip_last5_w = 0.20, 0.30, 0.50
        else:
            ip_season_w, ip_last10_w, ip_last5_w = 0.30, 0.40, 0.30

        expected_innings = round(min(
            round((season_avg_ip * ip_season_w) + (last10_avg_ip * ip_last10_w) + (last5_avg_ip * ip_last5_w), 2),
            pitch_based_ip
        ), 2)
        expected_bf = round(expected_innings * (season_avg_bf / season_avg_ip), 1)
        velo_factor = round(1.0 + ((recent_strike_pct - season_strike_pct) * 0.8), 3)

        league_avg_k_pct = league_avg_k_pct_vr if pitcher_hand == 'R' else league_avg_k_pct_vl
        team_data = requests.get(f"https://statsapi.mlb.com/api/v1/teams/stats?stats=season&group=hitting&season={season}&sportId=1").json()

        opp_k_pct = None
        for split in team_data['stats'][0]['splits']:
            if split['team']['name'] == opponent_team:
                opp_k_pct = round(int(split['stat']['strikeOuts']) / int(split['stat']['plateAppearances']), 3)
                break

        final_opp_k_pct = opp_k_pct or league_avg_k_pct
        lineup_k_pct = None

        if use_lineup:
            try:
                k_df = get_batter_k_pcts()
                check_date = before_date or date.today().strftime('%Y-%m-%d')
                sched_data = requests.get(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={check_date}&hydrate=lineups").json()
                if sched_data.get('dates'):
                    for game in sched_data['dates'][0]['games']:
                        ht = game['teams']['home']['team']['name']
                        at = game['teams']['away']['team']['name']
                        if home_team in ht or home_team in at:
                            lineups = game.get('lineups', {})
                            if lineups:
                                batting_lineup = lineups.get('awayPlayers', []) if opponent_team in at else lineups.get('homePlayers', [])
                                total = count = 0
                                for player in batting_lineup[:9]:
                                    match = k_df[k_df['full_name'].str.lower() == player['fullName'].lower()]
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
                sched_data = requests.get(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={check_date}&hydrate=officials").json()
                if sched_data.get('dates'):
                    for game in sched_data['dates'][0]['games']:
                        if home_team in game['teams']['home']['team']['name'] or home_team in game['teams']['away']['team']['name']:
                            for official in game.get('officials', []):
                                if official['officialType'] == 'Home Plate':
                                    umpire_name = official['official']['fullName']
                            break
                if umpire_name:
                    ump_data = requests.get("https://umpscorecards.com/api/umpires", headers={'User-Agent': 'Mozilla/5.0'}).json()
                    for ump in ump_data['rows']:
                        if ump['umpire'].lower() == umpire_name.lower():
                            umpire_factor = max(0.97, min(1.03, round(1.0 + ((round(ump['favor_abs_mean'], 3) - league_avg_favor) * 0.5), 3)))
                            break
            except:
                pass

        total_factor = 1.0
        if use_total:
            try:
                if before_date:
                    params = {'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': 'totals', 'oddsFormat': 'american', 'date': f"{before_date}T18:00:00Z"}
                    games_data = requests.get("https://api.the-odds-api.com/v4/historical/sports/baseball_mlb/odds", params=params).json().get('data', [])
                else:
                    params = {'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': 'totals', 'oddsFormat': 'american'}
                    games_data = requests.get("https://api.the-odds-api.com/v4/sports/baseball_mlb/odds", params=params).json()

                for game in games_data:
                    if home_team in game.get('home_team', '') or home_team in game.get('away_team', ''):
                        for bookmaker in game.get('bookmakers', []):
                            for market in bookmaker.get('markets', []):
                                if market['key'] == 'totals':
                                    game_total = market['outcomes'][0]['point']
                                    total_factor = max(0.95, min(1.05, round(1 - ((game_total - 8.5) * 0.02), 3)))
                            break
                        break
            except:
                pass

        base = expected_bf * pitcher_skill
        combined_factor = max(0.90, min(1.10, opp_factor * park_factor * umpire_factor * velo_factor * weather_adj * total_factor))
        final_projection = round(base * combined_factor, 1)

        return {
            'projection': final_projection, 'base': round(base, 2),
            'pitcher_hand': pitcher_hand, 'lineup_k_pct': final_opp_k_pct,
            'pitcher_skill': pitcher_skill, 'expected_bf': expected_bf,
            'expected_innings': expected_innings, 'expected_pitch_count': expected_pitch_count,
            'umpire_name': umpire_name, 'umpire_factor': umpire_factor,
            'opp_factor': opp_factor, 'park_factor': park_factor,
            'velo_factor': velo_factor, 'total_factor': total_factor,
            'combined_factor': round(combined_factor, 3), 'season_k_pct': season_k_pct,
            'last5_k': round(df['strikeouts'].head(5).mean(), 2),
            'last10_k': round(df['strikeouts'].head(10).mean(), 2),
            'last10_k_avg': last10_k_avg, 'last10_k_std': last10_k_std,
            'cv': cv, 'confidence_tier': confidence_tier,
            'season_avg_ip': season_avg_ip, 'pitches_per_inning': pitches_per_inning,
            'last3_pitches': last3_pitches, 'season_avg_pitches': season_avg_pitches,
            'pitch_count_factor': round(pitch_based_ip, 2),
            'lineup_factor': round(lineup_k_pct, 3) if lineup_k_pct else None,
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

        df = df[['GAME_DATE', 'MATCHUP', 'PTS', 'FGA', 'MIN']]
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
        last10_pts_std = round(last10_pts.std(), 2) if len(last10_pts) > 1 else 0.0
        cv = round(last10_pts_std / round(last10_pts.mean(), 2), 3) if round(last10_pts.mean(), 2) > 0 else 1.0

        if cv < 0.20: confidence_tier = "🟢 Elite Stability"
        elif cv < 0.35: confidence_tier = "🟡 Normal"
        elif cv < 0.50: confidence_tier = "🟠 High Variance"
        else: confidence_tier = "🔴 Pass Candidate"

        base = (last5_avg * 0.40) + (last10_avg * 0.30) + (season_ppg * 0.30)
        fga_factor = max(0.95, min(1.05, round(last5_fga / season_fga, 3) if season_fga > 0 else 1.0))

        adv_stats = leaguedashplayerstats.LeagueDashPlayerStats(season=season, per_mode_detailed='PerGame', measure_type_detailed_defense='Advanced')
        adv_df = adv_stats.get_data_frames()[0]
        player_adv = adv_df[adv_df['PLAYER_ID'] == player_id]
        usage_rate = round(float(player_adv['USG_PCT'].iloc[0]), 3) if not player_adv.empty else 0.20

        team_stats = leaguedashteamstats.LeagueDashTeamStats(season=season, per_mode_detailed='PerGame', measure_type_detailed_defense='Advanced')
        teams_df = team_stats.get_data_frames()[0]
        opp_full_name = nba_abbrev_to_name.get(opponent_abbrev, '')
        opp_team = teams_df[teams_df['TEAM_NAME'] == opp_full_name]
        opp_def_rating = round(float(opp_team['DEF_RATING'].iloc[0]), 1) if not opp_team.empty else league_avg_def_rating
        opp_pace = round(float(opp_team['PACE'].iloc[0]), 1) if not opp_team.empty else league_avg_pace

        home_games = df[df['MATCHUP'].str.contains('vs.')]
        away_games = df[df['MATCHUP'].str.contains('@')]
        home_ppg = round(home_games['PTS'].mean(), 1) if not home_games.empty else season_ppg
        away_ppg = round(away_games['PTS'].mean(), 1) if not away_games.empty else season_ppg
        location_adj = max(-2.0, min(2.0, round(home_ppg - season_ppg, 2) if home_or_away == 'home' else round(away_ppg - season_ppg, 2)))

        expected_minutes = round((season_mpg * 0.30) + (last10_min * 0.30) + (last5_min * 0.40), 1)

        df['GAME_DATE'] = pd.to_datetime(df['GAME_DATE'])
        days_rest = (datetime.today() - df['GAME_DATE'].iloc[-1]).days
        rest_adj = -1.5 if days_rest == 0 else (1.0 if days_rest >= 3 else 0)

        game_total = spread = None
        try:
            games_data = requests.get("https://api.the-odds-api.com/v4/sports/basketball_nba/odds",
                params={'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': 'totals,spreads', 'oddsFormat': 'american'}).json()
            for game in games_data:
                if home_team in game.get('home_team', '') or home_team in game.get('away_team', ''):
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

        team_total_adj = blowout_minutes_adj = 0
        implied_team_total = None
        if game_total and spread:
            if home_or_away == 'home':
                implied_team_total = round((game_total / 2) + (abs(spread) / 2 * (1 if spread < 0 else -1)), 1)
            else:
                implied_team_total = round((game_total / 2) - (abs(spread) / 2 * (1 if spread < 0 else -1)), 1)
            team_total_adj = round((implied_team_total - league_avg_team_score) * 0.08, 2)
            blowout_minutes_adj = -4 if abs(spread) >= 12 else (-2 if abs(spread) >= 9 else 0)

        final_expected_minutes = round(expected_minutes + blowout_minutes_adj, 1)
        pts_per_minute = round(season_ppg / season_mpg, 3) if season_mpg > 0 else 0
        minutes_pts_adj = round((final_expected_minutes - season_mpg) * pts_per_minute, 2)
        usage_adj = round((usage_rate - 0.20) * 10, 2)
        def_adj = round((opp_def_rating - league_avg_def_rating) * 0.2, 2)
        pace_adj = round((opp_pace - league_avg_pace) * 0.25, 2)

        raw_adjustment = max(-6.0, min(6.0, usage_adj + def_adj + pace_adj + team_total_adj + location_adj + rest_adj + minutes_pts_adj))
        final_projection = round((base + raw_adjustment) * fga_factor, 1)

        return {
            'projection': final_projection, 'base': round(base, 2),
            'season_ppg': season_ppg, 'last5_avg': last5_avg, 'last10_avg': last10_avg,
            'last10_pts_std': last10_pts_std, 'season_mpg': season_mpg,
            'expected_minutes': final_expected_minutes, 'usage_rate': usage_rate,
            'fga_factor': fga_factor, 'opp_def_rating': opp_def_rating, 'opp_pace': opp_pace,
            'location_adj': location_adj, 'rest_adj': rest_adj, 'team_total_adj': team_total_adj,
            'minutes_pts_adj': minutes_pts_adj, 'usage_adj': usage_adj, 'def_adj': def_adj,
            'pace_adj': pace_adj, 'implied_team_total': implied_team_total, 'game_total': game_total,
            'cv': cv, 'confidence_tier': confidence_tier, 'days_rest': days_rest
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

        if cv < 0.20: confidence_tier = "🟢 Elite Stability"
        elif cv < 0.35: confidence_tier = "🟡 Normal"
        elif cv < 0.50: confidence_tier = "🟠 High Variance"
        else: confidence_tier = "🔴 Pass Candidate"

        base = (last5_avg * 0.40) + (last10_avg * 0.30) + (season_apg * 0.30)
        tov_factor = max(0.95, min(1.05, round(last5_tov / season_tov, 3) if season_tov > 0 else 1.0))

        adv_stats = leaguedashplayerstats.LeagueDashPlayerStats(season=season, per_mode_detailed='PerGame', measure_type_detailed_defense='Advanced')
        adv_df = adv_stats.get_data_frames()[0]
        player_adv = adv_df[adv_df['PLAYER_ID'] == player_id]
        usage_rate = round(float(player_adv['USG_PCT'].iloc[0]), 3) if not player_adv.empty else 0.20
        ast_pct = round(float(player_adv['AST_PCT'].iloc[0]), 3) if not player_adv.empty else 0.15

        potential_assists = None
        potential_ast_adj = 0
        try:
            from nba_api.stats.endpoints import leaguedashptstats
            pt_stats = leaguedashptstats.LeagueDashPtStats(season=season, per_mode_simple='PerGame', player_or_team='Player', pt_measure_type='Passing')
            pt_df = pt_stats.get_data_frames()[0]
            player_pt = pt_df[pt_df['PLAYER_ID'] == player_id]
            if not player_pt.empty and 'POTENTIAL_AST' in player_pt.columns:
                potential_assists = round(float(player_pt['POTENTIAL_AST'].iloc[0]), 1)
                if potential_assists and season_apg > 0:
                    expected_ast_from_potential = potential_assists * 0.45
                    potential_ast_adj = max(-0.75, min(0.75, round((expected_ast_from_potential - season_apg) * 0.25, 2)))
        except:
            pass

        team_stats = leaguedashteamstats.LeagueDashTeamStats(season=season, per_mode_detailed='PerGame', measure_type_detailed_defense='Advanced')
        teams_df = team_stats.get_data_frames()[0]
        opp_full_name = nba_abbrev_to_name.get(opponent_abbrev, '')
        opp_team = teams_df[teams_df['TEAM_NAME'] == opp_full_name]
        opp_pace = round(float(opp_team['PACE'].iloc[0]), 1) if not opp_team.empty else league_avg_pace

        opp_ast_allowed = 25.0
        try:
            opp_basic = leaguedashteamstats.LeagueDashTeamStats(season=season, per_mode_detailed='PerGame', measure_type_detailed_defense='Base')
            opp_basic_df = opp_basic.get_data_frames()[0]
            opp_basic_row = opp_basic_df[opp_basic_df['TEAM_NAME'] == opp_full_name]
            if not opp_basic_row.empty and 'OPP_AST' in opp_basic_row.columns:
                opp_ast_allowed = round(float(opp_basic_row['OPP_AST'].iloc[0]), 1)
        except:
            pass

        opp_ast_adj = max(-0.5, min(0.5, round((opp_ast_allowed - 25.0) * 0.05, 2)))

        home_games = df[df['MATCHUP'].str.contains('vs.')]
        away_games = df[df['MATCHUP'].str.contains('@')]
        home_apg = round(home_games['AST'].mean(), 1) if not home_games.empty else season_apg
        away_apg = round(away_games['AST'].mean(), 1) if not away_games.empty else season_apg
        location_adj = max(-1.5, min(1.5, round(home_apg - season_apg, 2) if home_or_away == 'home' else round(away_apg - season_apg, 2)))

        expected_minutes = round((season_mpg * 0.30) + (last10_min * 0.30) + (last5_min * 0.40), 1)

        df['GAME_DATE'] = pd.to_datetime(df['GAME_DATE'])
        days_rest = (datetime.today() - df['GAME_DATE'].iloc[-1]).days
        rest_adj = -0.5 if days_rest == 0 else (0.3 if days_rest >= 3 else 0)

        game_total = spread = None
        try:
            games_data = requests.get("https://api.the-odds-api.com/v4/sports/basketball_nba/odds",
                params={'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': 'totals,spreads', 'oddsFormat': 'american'}).json()
            for game in games_data:
                if home_team in game.get('home_team', '') or home_team in game.get('away_team', ''):
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

        total_adj = max(-0.5, min(0.5, round((game_total - 225) * 0.015, 2))) if game_total else 0
        blowout_minutes_adj = -4 if (spread and abs(spread) >= 12) else (-2 if (spread and abs(spread) >= 9) else 0)
        pace_adj = round((opp_pace - league_avg_pace) * 0.12, 2)
        final_expected_minutes = round(expected_minutes + blowout_minutes_adj, 1)
        ast_per_minute = round(season_apg / season_mpg, 3) if season_mpg > 0 else 0
        minutes_ast_adj = round((final_expected_minutes - season_mpg) * ast_per_minute, 2)
        ast_pct_adj = max(-1.5, min(1.5, round((ast_pct - 0.25) * 6, 2)))

        raw_adjustment = max(-3.0, min(3.0, pace_adj + location_adj + rest_adj + minutes_ast_adj + ast_pct_adj + opp_ast_adj + total_adj + potential_ast_adj))
        final_projection = max(0, round(base + raw_adjustment, 1))

        return {
            'projection': final_projection, 'base': round(base, 2),
            'season_apg': season_apg, 'last5_avg': last5_avg, 'last10_avg': last10_avg,
            'last10_ast_std': last10_ast_std, 'season_mpg': season_mpg,
            'expected_minutes': final_expected_minutes, 'blowout_minutes_adj': blowout_minutes_adj,
            'usage_rate': usage_rate, 'ast_pct': ast_pct, 'ast_pct_adj': ast_pct_adj,
            'tov_factor': tov_factor, 'potential_assists': potential_assists,
            'potential_ast_adj': potential_ast_adj, 'opp_pace': opp_pace,
            'location_adj': location_adj, 'rest_adj': rest_adj, 'minutes_ast_adj': minutes_ast_adj,
            'pace_adj': pace_adj, 'opp_ast_adj': opp_ast_adj, 'opp_ast_allowed': opp_ast_allowed,
            'total_adj': total_adj, 'raw_adjustment': round(raw_adjustment, 2),
            'game_total': game_total, 'spread': spread, 'cv': cv,
            'confidence_tier': confidence_tier, 'days_rest': days_rest
        }
    except Exception as e:
        return None

pitchers_list = get_all_pitchers()

# ---- HELPER: RUN AND STORE EV RESULT ----
def compute_and_store_ev(name, info, result, proj, best_line, sport_key, session_key):
    edge = round(proj - best_line, 1)
    play = "⬆️ OVER" if edge > 0 else "⬇️ UNDER"
    direction = 'over' if edge > 0 else 'under'
    over_odds = info.get('FanDuel Over') or info.get('DraftKings Over')
    under_odds = info.get('FanDuel Under') or info.get('DraftKings Under')
    std_dev = result.get('last10_k_std', result.get('last10_pts_std', result.get('last10_ast_std', 0)))
    cv = result['cv']

    ev_result = analyze_prop(
        projection=proj, line=best_line, std_dev=std_dev, cv=cv,
        over_odds=over_odds or -110, under_odds=under_odds or -110,
        direction=direction, sport=sport_key
    )

    update = {
        'Projection': proj, 'Edge': edge, 'Play': play,
        'Tier': result['confidence_tier'],
        'Score': ev_result['score'] if ev_result else None,
        'Stars': ev_result['stars'] if ev_result else None,
        'EV%': ev_result['ev_pct'] if ev_result else None,
        'MM Tier': ev_result['tier'] if ev_result else None,
        'Model Prob': ev_result['model_prob'] if ev_result else None,
        'No Vig Prob': ev_result['no_vig_prob'] if ev_result else None,
        'Model Edge': ev_result['model_edge'] if ev_result else None,
        'Odds': over_odds if direction == 'over' else under_odds,
    }
    st.session_state[session_key][name].update(update)
    return ev_result, edge, play, direction, over_odds, under_odds

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
    st.markdown("""
        <div style='text-align: center; padding: 40px 0 20px 0;'>
            <h1 style='font-size: 2.5rem; margin-bottom: 8px;'>Sharp Data. Sharp Bets.</h1>
            <p style='color: #64748B; font-size: 1.1rem;'>Projections • +EV • Confidence Scores</p>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("""
        <div style='text-align: center; max-width: 700px; margin: 0 auto; padding-bottom: 30px;'>
            <p style='font-size: 1.05rem; color: #CBD5E1;'>
                Professional player prop projections powered by proprietary models and real-time +EV analysis.
                Find bets where both the numbers and the market agree.
            </p>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("""
            <div style='text-align: center; padding: 20px;'>
                <div style='font-size: 2rem;'>📈</div>
                <h3>Proprietary Projection Models</h3>
                <p style='color: #64748B;'>Accurate player projections built from advanced statistics, matchup data, pace, usage, workload, and betting market information.</p>
            </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown("""
            <div style='text-align: center; padding: 20px;'>
                <div style='font-size: 2rem;'>💰</div>
                <h3>Real-Time +EV Analysis</h3>
                <p style='color: #64748B;'>Automatically remove sportsbook vig, compare our probabilities to fair market odds, and identify positive expected value opportunities.</p>
            </div>
        """, unsafe_allow_html=True)
    with col3:
        st.markdown("""
            <div style='text-align: center; padding: 20px;'>
                <div style='font-size: 2rem;'>⭐</div>
                <h3>Model Metrics Score</h3>
                <p style='color: #64748B;'>Every bet receives a confidence score based on projection edge, expected value, historical consistency, and market alignment.</p>
            </div>
        """, unsafe_allow_html=True)

    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    col1.metric("⚾ MLB Strikeouts", "Live", "Model Active")
    col2.metric("🏈 NFL Models", "Coming Soon", "Season Starting")
    col3.metric("🏀 NBA Models", "Live", "Points + Assists")

    st.markdown("---")
    st.subheader("📌 How to Use Model Metrics")
    st.markdown("""
    1. **Select your sport** from the sidebar to access the available models.
    2. **Load today's props** to view live player prop lines from FanDuel and DraftKings.
    3. **Run projections** to compare our model's projections against the sportsbooks and identify potential value opportunities.
    4. **Check the Model Metrics Score** — higher scores mean both our model and the market agree there's value.
    5. **Click Log Bet** directly from the edges table to auto-fill your bet tracker with zero manual entry.
    """)

    st.markdown("---")
    st.markdown("""
        <div style='background: #0F172A; border-radius: 12px; padding: 30px; margin-top: 10px;'>
            <h3 style='margin-bottom: 12px;'>About Model Metrics</h3>
            <p style='color: #94A3B8; line-height: 1.7;'>
                Winning long-term isn't about predicting every game correctly — it's about consistently betting when the odds are in your favor.
            </p>
            <p style='color: #94A3B8; line-height: 1.7;'>
                Model Metrics combines proprietary projection models with professional expected value (+EV) analysis to help bettors identify wagers with long-term mathematical value.
                Every recommendation is backed by data, fair-odds pricing, and transparent confidence metrics.
            </p>
            <p style='color: #64748B; font-size: 0.9rem; margin-top: 16px;'>
                Proprietary Projection Models &nbsp;•&nbsp; No-Vig Pricing &nbsp;•&nbsp; +EV Analytics &nbsp;•&nbsp; Confidence Ratings
            </p>
        </div>
    """, unsafe_allow_html=True)

# ---- QUICK LOG BET MODAL ----
def show_log_bet_modal(name, info, sport):
    with st.expander(f"📝 Log Bet — {name}", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            bt_bet = st.number_input("Bet Amount ($)", value=None, placeholder="e.g. 100", key=f"modal_bet_{name}")
            bt_over_under = st.selectbox("Over or Under?", ["Over", "Under"], key=f"modal_ou_{name}")
        with col2:
            bt_actual = st.number_input("Actual Result (fill in after)", value=None, placeholder="e.g. 7", key=f"modal_actual_{name}")
            bt_result = st.selectbox("Result", ["Pending", "Win", "Loss"], key=f"modal_result_{name}")
        with col3:
            bt_closing_line = st.number_input("Closing Line (optional)", value=None, placeholder="e.g. 6.0", key=f"modal_close_{name}")

        if st.button(f"✅ Confirm Log Bet", key=f"modal_confirm_{name}", use_container_width=True):
            odds = info.get('Odds') or (info.get('FanDuel Over') if bt_over_under == 'Over' else info.get('FanDuel Under')) or -110
            bet_val = bt_bet or 0
            profit = calc_profit(bet_val, odds, bt_result)
            closing_line = bt_closing_line
            clv = None
            if closing_line and info.get('FanDuel Line'):
                clv = round(closing_line - info['FanDuel Line'], 2) if bt_over_under == 'Over' else round(info['FanDuel Line'] - closing_line, 2)

            save_bet({
                'date': str(date.today()),
                'pitcher': name,
                'projection': info.get('Projection') or 0,
                'opening_line': info.get('FanDuel Line') or info.get('DraftKings Line') or 0,
                'over_under': bt_over_under,
                'odds': odds,
                'bet_amount': bet_val,
                'result': bt_result,
                'actual': bt_actual or 0,
                'profit': profit,
                'sport': sport,
                'ev_pct': info.get('EV%'),
                'mm_score': info.get('Score'),
                'mm_tier': info.get('MM Tier'),
                'model_edge': info.get('Model Edge'),
                'no_vig_prob': info.get('No Vig Prob'),
                'model_prob': info.get('Model Prob'),
                'confidence_tier': info.get('Tier'),
                'closing_line': closing_line,
                'clv': clv,
            })
            st.success(f"✅ Bet logged for {name}!")
            st.rerun()

# ---- EDGES DISPLAY HELPER ----
def show_edges_table(session_key, sport_key, sport_label):
    if session_key not in st.session_state:
        return

    all_players = st.session_state[session_key]
    sorted_players = sorted(
        all_players.items(),
        key=lambda x: x[1]['Score'] if x[1]['Score'] is not None else -1,
        reverse=True
    )

    for name, info in sorted_players:
        col1, col2, col3, col4, col5, col6, col7, col8, col9, col10, col11 = st.columns([2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1])
        with col1:
            st.write(f"**{name}**")
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
            ev = info.get('EV%')
            st.write(f"EV: **{ev}%**" if ev is not None else "EV: —")
        with col9:
            score = info.get('Score')
            stars = info.get('Stars', '')
            st.write(f"{stars} **{score}**" if score is not None else "—")
            if info.get('MM Tier'):
                st.caption(info['MM Tier'])
        with col10:
            if st.button("▶️ Run", key=f"{session_key}_run_{name}"):
                st.session_state[f'run_trigger_{session_key}_{name}'] = True
                st.rerun()
        with col11:
            if info.get('Projection') is not None:
                if st.button("📝 Log", key=f"{session_key}_log_{name}"):
                    st.session_state[f'log_modal_{session_key}_{name}'] = True
                    st.rerun()

        if st.session_state.get(f'log_modal_{session_key}_{name}'):
            show_log_bet_modal(name, info, sport_label)

        st.divider()

# ---- MLB PAGE ----
elif nav == "⚾ MLB Models":
    st.title("⚾ MLB Strikeout Model")

    col_load, col_run_all = st.columns(2)

    with col_load:
        if st.button("📋 Load Today's Props", use_container_width=True):
            with st.spinner("Pulling today's props..."):
                try:
                    events_data = requests.get("https://api.the-odds-api.com/v4/sports/baseball_mlb/events",
                        params={'apiKey': ODDS_API_KEY, 'dateFormat': 'iso'}).json()
                    all_pitchers = {}

                    for event in events_data:
                        home = event['home_team']
                        away = event['away_team']
                        event_id = event['id']
                        props_data = requests.get(
                            f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events/{event_id}/odds",
                            params={'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': 'pitcher_strikeouts', 'oddsFormat': 'american'}
                        ).json()

                        for bookmaker in props_data.get('bookmakers', []):
                            if bookmaker['key'] in ['fanduel', 'draftkings']:
                                book_name = bookmaker['title']
                                for market in bookmaker.get('markets', []):
                                    if market['key'] == 'pitcher_strikeouts':
                                        for outcome in market['outcomes']:
                                            pitcher = outcome['description']
                                            if pitcher not in all_pitchers:
                                                all_pitchers[pitcher] = {
                                                    'home': home, 'away': away,
                                                    'FanDuel Line': None, 'FanDuel Over': None, 'FanDuel Under': None,
                                                    'DraftKings Line': None, 'DraftKings Over': None, 'DraftKings Under': None,
                                                    'Projection': None, 'Edge': None, 'Play': None,
                                                    'Tier': None, 'Score': None, 'Stars': None,
                                                    'EV%': None, 'MM Tier': None, 'Model Prob': None,
                                                    'No Vig Prob': None, 'Model Edge': None, 'Odds': None
                                                }
                                            if 'FanDuel' in book_name:
                                                all_pitchers[pitcher]['FanDuel Line'] = outcome['point']
                                                if outcome['name'] == 'Over':
                                                    all_pitchers[pitcher]['FanDuel Over'] = outcome['price']
                                                else:
                                                    all_pitchers[pitcher]['FanDuel Under'] = outcome['price']
                                            elif 'DraftKings' in book_name:
                                                all_pitchers[pitcher]['DraftKings Line'] = outcome['point']
                                                if outcome['name'] == 'Over':
                                                    all_pitchers[pitcher]['DraftKings Over'] = outcome['price']
                                                else:
                                                    all_pitchers[pitcher]['DraftKings Under'] = outcome['price']

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
                        best_line = info['FanDuel Line'] or info['DraftKings Line']
                        if best_line:
                            ev_result, edge, play, direction, over_odds, under_odds = compute_and_store_ev(
                                pitcher, info, result, proj, best_line, 'mlb_strikeouts', 'all_pitchers'
                            )
                            save_prediction({
                                'date': date.today().strftime('%Y-%m-%d'),
                                'pitcher': pitcher, 'opponent': opp, 'home_team': h,
                                'projection': proj, 'base': result['base'], 'book_line': best_line,
                                'edge': edge, 'opp_factor': result['opp_factor'],
                                'park_factor': result['park_factor'], 'umpire_factor': result['umpire_factor'],
                                'velo_factor': result['velo_factor'], 'total_factor': result['total_factor'],
                                'pitch_count_factor': result['pitch_count_factor'],
                                'lineup_factor': result['lineup_factor'],
                                'cv': result['cv'], 'confidence_tier': result['confidence_tier'],
                                'actual': None, 'sport': 'MLB'
                            })

                status_text.text(f"✅ Done! All {total} projections complete.")
                progress_bar.progress(1.0)
                st.rerun()

    # Handle individual run triggers
    if 'all_pitchers' in st.session_state:
        season = st.session_state.get('season', '2026')
        for pitcher, info in list(st.session_state['all_pitchers'].items()):
            if st.session_state.get(f'run_trigger_all_pitchers_{pitcher}'):
                st.session_state[f'run_trigger_all_pitchers_{pitcher}'] = False
                with st.spinner(f"Running {pitcher}..."):
                    _, opp, h = get_pitcher_game_info(pitcher)
                    if not opp:
                        opp = info['away']
                        h = info['home']
                    result = run_projection(pitcher, opp, h, season)
                    if result:
                        proj = result['projection']
                        best_line = info['FanDuel Line'] or info['DraftKings Line']
                        if best_line:
                            compute_and_store_ev(pitcher, info, result, proj, best_line, 'mlb_strikeouts', 'all_pitchers')
                            save_prediction({
                                'date': date.today().strftime('%Y-%m-%d'),
                                'pitcher': pitcher, 'opponent': opp, 'home_team': h,
                                'projection': proj, 'base': result['base'], 'book_line': best_line,
                                'edge': round(proj - best_line, 1),
                                'opp_factor': result['opp_factor'], 'park_factor': result['park_factor'],
                                'umpire_factor': result['umpire_factor'], 'velo_factor': result['velo_factor'],
                                'total_factor': result['total_factor'], 'pitch_count_factor': result['pitch_count_factor'],
                                'lineup_factor': result['lineup_factor'],
                                'cv': result['cv'], 'confidence_tier': result['confidence_tier'],
                                'actual': None, 'sport': 'MLB'
                            })
                st.rerun()

    show_edges_table('all_pitchers', 'mlb_strikeouts', 'MLB')

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

    def run_nba_all(session_key, run_fn, sport_key, sport_label, prop_market):
        col_load, col_run_all = st.columns(2)

        with col_load:
            if st.button(f"📋 Load Today's Props", use_container_width=True, key=f"load_{session_key}"):
                with st.spinner("Pulling props..."):
                    try:
                        events_data = requests.get("https://api.the-odds-api.com/v4/sports/basketball_nba/events",
                            params={'apiKey': ODDS_API_KEY, 'dateFormat': 'iso'}).json()
                        all_players = {}

                        for event in events_data:
                            home = event['home_team']
                            away = event['away_team']
                            event_id = event['id']
                            props_data = requests.get(
                                f"https://api.the-odds-api.com/v4/sports/basketball_nba/events/{event_id}/odds",
                                params={'apiKey': ODDS_API_KEY, 'regions': 'us', 'markets': prop_market, 'oddsFormat': 'american'}
                            ).json()

                            for bookmaker in props_data.get('bookmakers', []):
                                if bookmaker['key'] in ['fanduel', 'draftkings']:
                                    book_name = bookmaker['title']
                                    for market in bookmaker.get('markets', []):
                                        if market['key'] == prop_market:
                                            for outcome in market['outcomes']:
                                                player = outcome['description']
                                                if player not in all_players:
                                                    all_players[player] = {
                                                        'home': home, 'away': away,
                                                        'FanDuel Line': None, 'FanDuel Over': None, 'FanDuel Under': None,
                                                        'DraftKings Line': None, 'DraftKings Over': None, 'DraftKings Under': None,
                                                        'Projection': None, 'Edge': None, 'Play': None,
                                                        'Tier': None, 'Score': None, 'Stars': None,
                                                        'EV%': None, 'MM Tier': None, 'Model Prob': None,
                                                        'No Vig Prob': None, 'Model Edge': None, 'Odds': None
                                                    }
                                                if 'FanDuel' in book_name:
                                                    all_players[player]['FanDuel Line'] = outcome['point']
                                                    if outcome['name'] == 'Over':
                                                        all_players[player]['FanDuel Over'] = outcome['price']
                                                    else:
                                                        all_players[player]['FanDuel Under'] = outcome['price']
                                                elif 'DraftKings' in book_name:
                                                    all_players[player]['DraftKings Line'] = outcome['point']
                                                    if outcome['name'] == 'Over':
                                                        all_players[player]['DraftKings Over'] = outcome['price']
                                                    else:
                                                        all_players[player]['DraftKings Under'] = outcome['price']

                        st.session_state[session_key] = all_players
                        st.session_state['nba_season'] = '2025-26'
                        st.success(f"Loaded {len(all_players)} players!")
                    except Exception as e:
                        st.error(f"Error: {e}")

        with col_run_all:
            if st.button("🚀 Run All Projections", use_container_width=True, key=f"run_all_{session_key}"):
                if session_key not in st.session_state:
                    st.warning("Load today's props first!")
                else:
                    all_players = st.session_state[session_key]
                    season = st.session_state.get('nba_season', '2025-26')
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    total = len(all_players)

                    for i, (player, info) in enumerate(all_players.items()):
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

                        result = run_fn(player, opp_abbrev, home_team, away_team, home_or_away, season)
                        if result:
                            proj = result['projection']
                            best_line = info['FanDuel Line'] or info['DraftKings Line']
                            if best_line:
                                compute_and_store_ev(player, info, result, proj, best_line, sport_key, session_key)

                    status_text.text(f"✅ Done! All {total} projections complete.")
                    progress_bar.progress(1.0)
                    st.rerun()

        # Handle individual run triggers
        if session_key in st.session_state:
            season = st.session_state.get('nba_season', '2025-26')
            for player, info in list(st.session_state[session_key].items()):
                if st.session_state.get(f'run_trigger_{session_key}_{player}'):
                    st.session_state[f'run_trigger_{session_key}_{player}'] = False
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
                        result = run_fn(player, opp_abbrev, home_team, away_team, home_or_away, season)
                        if result:
                            proj = result['projection']
                            best_line = info['FanDuel Line'] or info['DraftKings Line']
                            if best_line:
                                compute_and_store_ev(player, info, result, proj, best_line, sport_key, session_key)
                    st.rerun()

        show_edges_table(session_key, sport_key, sport_label)

    if nba_model_select == "NBA Points":
        run_nba_all('all_nba_players', run_nba_points_projection, 'nba_points', 'NBA', 'player_points')
    else:
        run_nba_all('all_nba_assist_players', run_nba_assists_projection, 'nba_assists', 'NBA_AST', 'player_assists')

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
        bt_model_edge = st.number_input("Model Edge", value=None, placeholder="e.g. 0.9")
    with col2:
        bt_date = st.date_input("Date")
        bt_over_under = st.selectbox("Over or Under?", ["Over", "Under"])
        bt_odds = st.number_input("Odds (e.g. -140 or +110)", value=None, placeholder="e.g. -140")
        bt_actual = st.number_input("Actual Result", value=None, placeholder="e.g. 7")
        bt_ev_pct = st.number_input("EV% at time of bet", value=None, placeholder="e.g. 6.2")
    with col3:
        bt_result = st.selectbox("Result", ["Pending", "Win", "Loss"])
        bt_mm_score = st.number_input("MM Score", value=None, placeholder="e.g. 82", step=1)
        bt_mm_tier = st.selectbox("MM Tier", ["", "🥇 Consensus Gold", "📊 Model Edge", "💰 +EV Only", "⚪ Low Signal"])
        bt_confidence_tier = st.selectbox("Confidence Tier", ["", "🟢 Elite Stability", "🟡 Normal", "🟠 High Variance", "🔴 Pass Candidate"])
        bt_no_vig_prob = st.number_input("No-Vig Prob", value=None, placeholder="e.g. 0.52")
        bt_model_prob = st.number_input("Model Prob", value=None, placeholder="e.g. 0.61")

    if st.button("Log Bet"):
        odds_val = bt_odds or -110
        bet_val = bt_bet or 0
        profit = calc_profit(bet_val, odds_val, bt_result)
        save_bet({
            'date': str(bt_date), 'pitcher': bt_player,
            'projection': bt_projection or 0, 'opening_line': bt_opening_line or 0,
            'over_under': bt_over_under, 'odds': odds_val,
            'bet_amount': bet_val, 'result': bt_result,
            'actual': bt_actual or 0, 'profit': profit,
            'sport': bet_sport, 'ev_pct': bt_ev_pct,
            'mm_score': int(bt_mm_score) if bt_mm_score else None,
            'mm_tier': bt_mm_tier or None,
            'model_edge': bt_model_edge, 'no_vig_prob': bt_no_vig_prob,
            'model_prob': bt_model_prob, 'confidence_tier': bt_confidence_tier or None,
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

            quality_cols = st.columns(3)
            if 'ev_pct' in bets_df.columns and bets_df['ev_pct'].notna().any():
                quality_cols[0].metric("Avg EV%", f"{round(bets_df['ev_pct'].dropna().mean(), 2)}%")
            if 'mm_score' in bets_df.columns and bets_df['mm_score'].notna().any():
                quality_cols[1].metric("Avg MM Score", f"{round(bets_df['mm_score'].dropna().mean(), 1)}")
            if 'model_edge' in bets_df.columns and bets_df['model_edge'].notna().any():
                quality_cols[2].metric("Avg Model Edge", f"{round(bets_df['model_edge'].dropna().mean(), 2)}")

        if 'mm_tier' in bets_df.columns and bets_df['mm_tier'].notna().any():
            st.markdown("---")
            st.subheader("🥇 Performance by MM Tier")
            settled_with_tier = settled[settled['mm_tier'].notna()] if 'mm_tier' in settled.columns else pd.DataFrame()
            if not settled_with_tier.empty:
                tier_perf = []
                for tier in settled_with_tier['mm_tier'].unique():
                    t_df = settled_with_tier[settled_with_tier['mm_tier'] == tier]
                    t_wins = len(t_df[t_df['result'] == 'Win'])
                    t_total = len(t_df)
                    t_wagered = round(t_df['bet_amount'].sum(), 2)
                    t_roi = round(t_df['profit'].sum() / t_wagered * 100, 1) if t_wagered > 0 else 0
                    tier_perf.append({'Tier': tier, 'Bets': t_total, 'Win %': f"{round(t_wins / t_total * 100, 1)}%", 'ROI': f"{t_roi}%", 'Profit': f"${round(t_df['profit'].sum(), 2)}"})
                st.dataframe(pd.DataFrame(tier_perf), use_container_width=True)

        if 'ev_pct' in bets_df.columns and not settled.empty and settled['ev_pct'].notna().any():
            st.markdown("---")
            st.subheader("💰 Performance by EV%")
            ev_settled = settled[settled['ev_pct'].notna()]
            ev_buckets = [('0–2%', 0, 2), ('2–4%', 2, 4), ('4–6%', 4, 6), ('6%+', 6, 999)]
            ev_data = []
            for label, low, high in ev_buckets:
                bucket = ev_settled[(ev_settled['ev_pct'] >= low) & (ev_settled['ev_pct'] < high)]
                if len(bucket) > 0:
                    b_wagered = round(bucket['bet_amount'].sum(), 2)
                    b_roi = round(bucket['profit'].sum() / b_wagered * 100, 1) if b_wagered > 0 else 0
                    ev_data.append({'EV%': label, 'Bets': len(bucket), 'ROI': f"{b_roi}%", 'Profit': f"${round(bucket['profit'].sum(), 2)}"})
            if ev_data:
                st.dataframe(pd.DataFrame(ev_data), use_container_width=True)

        if 'mm_score' in bets_df.columns and not settled.empty and settled['mm_score'].notna().any():
            st.markdown("---")
            st.subheader("⭐ Performance by MM Score")
            score_settled = settled[settled['mm_score'].notna()]
            score_buckets = [('90–100', 90, 100), ('80–89', 80, 89), ('70–79', 70, 79), ('60–69', 60, 69), ('<60', 0, 59)]
            score_data = []
            for label, low, high in score_buckets:
                bucket = score_settled[(score_settled['mm_score'] >= low) & (score_settled['mm_score'] <= high)]
                if len(bucket) > 0:
                    b_wagered = round(bucket['bet_amount'].sum(), 2)
                    b_roi = round(bucket['profit'].sum() / b_wagered * 100, 1) if b_wagered > 0 else 0
                    score_data.append({'Score Range': label, 'Bets': len(bucket), 'ROI': f"{b_roi}%", 'Profit': f"${round(bucket['profit'].sum(), 2)}"})
            if score_data:
                st.dataframe(pd.DataFrame(score_data), use_container_width=True)

        if 'sport' in bets_df.columns and not settled.empty:
            st.markdown("---")
            st.subheader("📊 Performance by Sport")
            sport_data = []
            for sport in settled['sport'].unique():
                s_df = settled[settled['sport'] == sport]
                s_wins = len(s_df[s_df['result'] == 'Win'])
                s_total = len(s_df)
                s_wagered = round(s_df['bet_amount'].sum(), 2)
                s_roi = round(s_df['profit'].sum() / s_wagered * 100, 1) if s_wagered > 0 else 0
                avg_ev = round(s_df['ev_pct'].dropna().mean(), 2) if 'ev_pct' in s_df.columns and s_df['ev_pct'].notna().any() else 'N/A'
                avg_score = round(s_df['mm_score'].dropna().mean(), 1) if 'mm_score' in s_df.columns and s_df['mm_score'].notna().any() else 'N/A'
                sport_data.append({
                    'Sport': sport, 'Bets': s_total,
                    'Win %': f"{round(s_wins / s_total * 100, 1)}%" if s_total > 0 else '0%',
                    'ROI': f"{s_roi}%", 'Avg EV%': avg_ev, 'Avg Score': avg_score
                })
            if sport_data:
                st.dataframe(pd.DataFrame(sport_data), use_container_width=True)

        if 'closing_line' in bets_df.columns and bets_df['closing_line'].notna().any():
            st.markdown("---")
            st.subheader("📈 Closing Line Value (CLV)")
            clv_df = bets_df[bets_df['closing_line'].notna() & bets_df['opening_line'].notna()].copy()
            if not clv_df.empty:
                clv_df['clv_points'] = clv_df.apply(
                    lambda r: r['closing_line'] - r['opening_line'] if r['over_under'] == 'Over' else r['opening_line'] - r['closing_line'],
                    axis=1
                )
                beat_close = len(clv_df[clv_df['clv_points'] > 0])
                avg_clv = round(clv_df['clv_points'].mean(), 3)
                col1, col2 = st.columns(2)
                col1.metric("Avg CLV", f"{avg_clv} pts")
                col2.metric("Beat Closing Line", f"{round(beat_close / len(clv_df) * 100, 1)}%")

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
            tiers = [('0.0 to 0.4', 0.0, 0.4), ('0.5 to 0.9', 0.5, 0.9), ('1.0 to 1.4', 1.0, 1.4), ('1.5+', 1.5, 99)]
            tier_data = []
            for label, low, high in tiers:
                for direction in ['⬆️ OVER', '⬇️ UNDER']:
                    dir_df = settled_with_data[settled_with_data['over_under'].str.lower() == direction.split(' ')[1].lower()]
                    tier_df = dir_df[(dir_df['edge'] >= low) & (dir_df['edge'] <= high)]
                    if len(tier_df) > 0:
                        win_rate = round(tier_df['win'].mean() * 100, 1)
                        tier_data.append({'Direction': direction, 'Edge Tier': label, 'Bets': len(tier_df), 'Wins': int(tier_df['win'].sum()), 'Win Rate': f"{win_rate}%"})
            if tier_data:
                st.dataframe(pd.DataFrame(tier_data), use_container_width=True)

        st.markdown("---")
        st.subheader("📝 All Bets")

        display_df = bets_df.drop(columns=[c for c in ['id', 'created_at', 'user_id'] if c in bets_df.columns], errors='ignore')

        edited_df = st.data_editor(
            display_df,
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                'result': st.column_config.SelectboxColumn('Result', options=['Pending', 'Win', 'Loss']),
                'actual': st.column_config.NumberColumn('Actual', min_value=0),
                'opening_line': st.column_config.NumberColumn('Book Line', min_value=0.0, step=0.5),
                'closing_line': st.column_config.NumberColumn('Closing Line', min_value=0.0, step=0.5),
                'projection': st.column_config.NumberColumn('Projection', min_value=0.0, step=0.1),
                'bet_amount': st.column_config.NumberColumn('Bet ($)', min_value=0.0),
                'odds': st.column_config.NumberColumn('Odds'),
                'profit': st.column_config.NumberColumn('Profit ($)'),
                'over_under': st.column_config.SelectboxColumn('O/U', options=['Over', 'Under']),
                'sport': st.column_config.SelectboxColumn('Sport', options=['MLB', 'NBA', 'NBA_AST', 'NFL']),
                'ev_pct': st.column_config.NumberColumn('EV%'),
                'mm_score': st.column_config.NumberColumn('MM Score'),
                'mm_tier': st.column_config.SelectboxColumn('MM Tier', options=['🥇 Consensus Gold', '📊 Model Edge', '💰 +EV Only', '⚪ Low Signal']),
                'confidence_tier': st.column_config.SelectboxColumn('Conf Tier', options=['🟢 Elite Stability', '🟡 Normal', '🟠 High Variance', '🔴 Pass Candidate']),
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
                            'actual': b.get('actual'), 'result': b.get('result'),
                            'odds': b.get('odds'), 'bet_amount': b.get('bet_amount'),
                            'opening_line': b.get('opening_line'), 'closing_line': b.get('closing_line'),
                            'projection': b.get('projection'), 'over_under': b.get('over_under'),
                            'profit': b['profit'], 'sport': b.get('sport', 'MLB'),
                            'ev_pct': b.get('ev_pct'), 'mm_score': b.get('mm_score'),
                            'mm_tier': b.get('mm_tier'), 'model_edge': b.get('model_edge'),
                            'no_vig_prob': b.get('no_vig_prob'), 'model_prob': b.get('model_prob'),
                            'confidence_tier': b.get('confidence_tier')
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
                    base = pred['base']
                    opp_f = pred['opp_factor']
                    park_f = pred['park_factor'] if config['use_park'] else 1.0
                    ump_f = pred['umpire_factor'] if config['use_umpire'] else 1.0
                    velo_f = pred['velo_factor']
                    total_f = pred['total_factor'] if config['use_total'] else 1.0
                    combined = max(0.90, min(1.10, opp_f * park_f * ump_f * velo_f * total_f))
                    proj = round(base * combined, 1)
                    errors.append(abs(proj - pred['actual']))
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
            conversion_rate = st.select_slider("Potential Assist Conversion Rate", options=[0.42, 0.45, 0.48], value=0.45)
            st.caption(f"Testing: expected assists = potential assists × {conversion_rate}")
            if preds_with_actual:
                errors_by_rate = {rate: round(sum(abs(p['projection'] - p['actual']) for p in preds_with_actual) / len(preds_with_actual), 2) for rate in [0.42, 0.45, 0.48]}
                rate_df = pd.DataFrame([{'Conversion Rate': k, 'MAE': v} for k, v in errors_by_rate.items()])
                st.dataframe(rate_df, use_container_width=True)
                best_rate = min(errors_by_rate, key=errors_by_rate.get)
                st.success(f"✅ Best conversion rate so far: **{best_rate}** with MAE of **{errors_by_rate[best_rate]}**")

        preds_with_tier = [p for p in preds_with_actual if p.get('confidence_tier')]
        if preds_with_tier:
            st.markdown("---")
            st.subheader("🎯 MAE by Confidence Tier")
            tier_df = pd.DataFrame(preds_with_tier)
            tier_df['error'] = (tier_df['projection'] - tier_df['actual']).abs()
            tier_summary = tier_df.groupby('confidence_tier').agg(Predictions=('error', 'count'), MAE=('error', 'mean')).reset_index()
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
                        result = run_projection(starter['pitcher'], starter['opponent'], starter['home_team'], backtest_season, before_date=date_str)
                        actual_k = get_actual_strikeouts(starter['game_pk'], starter['pitcher'])

                        if result and actual_k is not None:
                            results.append({
                                'Pitcher': starter['pitcher'],
                                'Matchup': f"{starter['opponent']} @ {starter['home_team']}",
                                'Projection': result['projection'], 'Actual K': actual_k,
                                'Error': round(abs(result['projection'] - actual_k), 1),
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

                    for i, game in enumerate(games):
                        status_text.text(f"Processing game {i+1} of {len(games)}")
                        progress_bar.progress((i+1) / len(games))

                        home_abbrev = game.get('home_team_abbrev', '')
                        away_abbrev = game.get('away_team_abbrev', '')
                        home_name = nba_abbrev_to_name.get(home_abbrev, '')
                        away_name = nba_abbrev_to_name.get(away_abbrev, '')

                        try:
                            box_url = f"https://stats.nba.com/stats/boxscoretraditionalv2?GameID={game['game_id']}&StartPeriod=0&EndPeriod=10&StartRange=0&EndRange=28800&RangeType=0"
                            box_data = requests.get(box_url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.nba.com'}).json()
                            player_stats = box_data['resultSets'][0]
                            headers_list = player_stats['headers']

                            for row in player_stats['rowSet']:
                                player = dict(zip(headers_list, row))
                                player_name = player['PLAYER_NAME']
                                actual_val = player.get('AST' if is_assists else 'PTS', None)
                                if actual_val is None:
                                    continue

                                team_abbrev = player.get('TEAM_ABBREVIATION', '')
                                home_or_away = 'home' if team_abbrev == home_abbrev else 'away'
                                opp_abbrev = away_abbrev if home_or_away == 'home' else home_abbrev

                                if is_assists:
                                    result = run_nba_assists_projection(player_name, opp_abbrev, home_name, away_name, home_or_away, backtest_season_nba)
                                else:
                                    result = run_nba_points_projection(player_name, opp_abbrev, home_name, away_name, home_or_away, backtest_season_nba)

                                if result:
                                    results.append({
                                        'Player': player_name,
                                        'Matchup': f"{away_name} @ {home_name}",
                                        'Projection': result['projection'], 'Actual': actual_val,
                                        'Error': round(abs(result['projection'] - actual_val), 1),
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
            tier_summary = results_df.groupby('Tier').agg(Predictions=('Error', 'count'), MAE=('Error', 'mean')).reset_index()
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
