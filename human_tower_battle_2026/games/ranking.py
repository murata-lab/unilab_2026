import json
import os
from datetime import datetime
from pathlib import Path

try:
    from paths import RANKING_FILE
except ImportError:
    RANKING_FILE = Path(__file__).resolve().with_name("ranking.json")

class RankingManager:
    def __init__(self, filename=None):
        self.filename = Path(filename) if filename else RANKING_FILE
        self.rankings = self.load_rankings()

    def load_rankings(self):
        """ランキングデータを読み込む"""
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {"daily": [], "all_time": []}
        return {"daily": [], "all_time": []}

    def save_rankings(self):
        """ランキングデータを保存する"""
        self.filename.parent.mkdir(parents=True, exist_ok=True)
        with open(self.filename, 'w', encoding='utf-8') as f:
            json.dump(self.rankings, f, ensure_ascii=False, indent=2)

    def add_score(self, score):
        """新しいスコアを追加"""
        today = datetime.now().strftime("%Y-%m-%d")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        # 日別ランキングに追加
        daily_entry = {
            "score": score,
            "date": today,
            "timestamp": timestamp
        }
        self.rankings["daily"].append(daily_entry)

        # 全体ランキングに追加
        all_time_entry = {
            "score": score,
            "date": today,
            "timestamp": timestamp
        }
        self.rankings["all_time"].append(all_time_entry)

        # ソート（スコアの高い順）
        self.rankings["daily"].sort(key=lambda x: x["score"], reverse=True)
        self.rankings["all_time"].sort(key=lambda x: x["score"], reverse=True)

        # 上位10位まで保持
        self.rankings["daily"] = self.rankings["daily"][:10]
        self.rankings["all_time"] = self.rankings["all_time"][:10]

        self.save_rankings()

    def get_daily_rankings(self):
        """本日のランキングを取得"""
        today = datetime.now().strftime("%Y-%m-%d")
        daily_scores = [entry for entry in self.rankings["daily"] if entry["date"] == today]
        return daily_scores[:5]  # 上位5位まで

    def get_all_time_rankings(self):
        """全体ランキングを取得"""
        return self.rankings["all_time"][:5]  # 上位5位まで

    def get_player_rank(self, score):
        """プレイヤーの順位を取得"""
        today = datetime.now().strftime("%Y-%m-%d")
        daily_scores = [entry["score"] for entry in self.rankings["daily"] if entry["date"] == today]

        # 同じスコアの場合は同じ順位
        rank = 1
        for s in daily_scores:
            if s > score:
                rank += 1
        return rank
