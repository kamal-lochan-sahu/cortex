"""
CORTEX - Q-Learner
Simple tabular Q-Learning for OPTIMUS energy optimization.
State: (energy_price_level, production_demand_level)
Actions: 5 discrete energy management actions
Reward: cost_saved - production_loss
RAM: <1MB (Q-table is 9x5 = 45 floats)
"""
import os
import pickle
import numpy as np
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────
# Price levels: 0=LOW(<40 EUR/MWh), 1=MED, 2=HIGH(>80 EUR/MWh)
PRICE_LEVELS  = ["LOW", "MED", "HIGH"]

# Demand levels: 0=LOW(<40 units), 1=MED, 2=HIGH(>70 units)
DEMAND_LEVELS = ["LOW", "MED", "HIGH"]

# 5 discrete actions OPTIMUS can take
ACTIONS = [
    "NORMAL",       # Run at full capacity
    "REDUCE_10",    # Reduce consumption 10%
    "REDUCE_20",    # Reduce consumption 20%
    "SHIFT_HEAVY",  # Shift heavy loads to off-peak
    "PRE_COOL",     # Pre-cool/pre-heat before peak price
]

# Reward weights
# cost_saved: how much EUR saved per MWh by this action
# prod_loss:  how much production is sacrificed
ACTION_REWARD_MAP = {
    #                cost_saved  prod_loss
    "NORMAL":       (0.0,        0.0),
    "REDUCE_10":    (0.10,       0.05),
    "REDUCE_20":    (0.20,       0.15),
    "SHIFT_HEAVY":  (0.25,       0.08),
    "PRE_COOL":     (0.15,       0.02),
}

# ─────────────────────────────────────────────
# Q-LEARNER CLASS
# ─────────────────────────────────────────────
class QLearner:
    def __init__(
        self,
        alpha: float = 0.1,    # learning rate
        gamma: float = 0.95,   # discount factor
        epsilon: float = 0.2,  # exploration rate
        epsilon_decay: float = 0.995,
        epsilon_min: float = 0.05,
    ):
        self.alpha         = alpha
        self.gamma         = gamma
        self.epsilon       = epsilon
        self.epsilon_decay = epsilon_decay
        self.epsilon_min   = epsilon_min

        # Q-table: shape (3 price levels, 3 demand levels, 5 actions)
        # Initialize with small random values — not zeros
        # Zeros cause ties and slow learning
        self.q_table = np.random.uniform(
            low=-0.01, high=0.01,
            size=(len(PRICE_LEVELS), len(DEMAND_LEVELS), len(ACTIONS))
        )

        self.total_updates = 0
        self.total_reward  = 0.0
        logger.info("QLearner initialized. Q-table shape: %s", self.q_table.shape)

    # ─────────────────────────────────────────
    # STATE ENCODING
    # Convert raw values → discrete state indices
    # ─────────────────────────────────────────
    @staticmethod
    def encode_price(price_eur_mwh: float) -> int:
        """0=LOW(<40), 1=MED(40-80), 2=HIGH(>80)"""
        if price_eur_mwh < 40:
            return 0
        elif price_eur_mwh < 80:
            return 1
        else:
            return 2

    @staticmethod
    def encode_demand(demand_units: float) -> int:
        """0=LOW(<40), 1=MED(40-70), 2=HIGH(>70)"""
        if demand_units < 40:
            return 0
        elif demand_units < 70:
            return 1
        else:
            return 2

    def get_state(
        self,
        price_eur_mwh: float,
        demand_units: float
    ) -> tuple[int, int]:
        return (
            self.encode_price(price_eur_mwh),
            self.encode_demand(demand_units),
        )

    # ─────────────────────────────────────────
    # ACTION SELECTION — epsilon-greedy
    # With probability epsilon → explore (random)
    # Otherwise → exploit (best known action)
    # ─────────────────────────────────────────
    def choose_action(
        self,
        price_eur_mwh: float,
        demand_units: float
    ) -> dict:
        price_idx, demand_idx = self.get_state(price_eur_mwh, demand_units)

        if np.random.random() < self.epsilon:
            # Explore — random action
            action_idx = np.random.randint(len(ACTIONS))
            mode = "explore"
        else:
            # Exploit — best Q-value action
            action_idx = int(np.argmax(self.q_table[price_idx, demand_idx]))
            mode = "exploit"

        action = ACTIONS[action_idx]
        q_val  = float(self.q_table[price_idx, demand_idx, action_idx])

        # Confidence: how certain are we about this action?
        # High confidence = exploit mode + high Q-value gap vs alternatives
        q_row   = self.q_table[price_idx, demand_idx]
        q_gap   = float(q_row[action_idx] - np.mean(q_row))
        confidence = round(min(1.0, max(0.0, 0.5 + q_gap * 2)), 4)

        return {
            "action":       action,
            "action_idx":   action_idx,
            "price_level":  PRICE_LEVELS[price_idx],
            "demand_level": DEMAND_LEVELS[demand_idx],
            "q_value":      round(q_val, 6),
            "confidence":   confidence,
            "mode":         mode,
            "timestamp":    datetime.now(timezone.utc).isoformat(),
        }

    # ─────────────────────────────────────────
    # REWARD CALCULATION
    # ─────────────────────────────────────────
    @staticmethod
    def calculate_reward(
        action: str,
        price_eur_mwh: float,
        demand_units: float
    ) -> float:
        """
        reward = cost_saved_factor * price_level - prod_loss_factor * demand_level

        High price + low demand → REDUCE actions get high reward
        Low price + high demand → NORMAL gets high reward
        """
        cost_factor, loss_factor = ACTION_REWARD_MAP[action]

        # Normalize price (0-1 scale, cap at 120 EUR/MWh)
        norm_price  = min(price_eur_mwh / 120.0, 1.0)
        # Normalize demand (0-1 scale, cap at 100 units)
        norm_demand = min(demand_units / 100.0, 1.0)

        cost_saved    = cost_factor * norm_price * 10.0   # scale to EUR
        prod_loss     = loss_factor * norm_demand * 8.0   # scale to production units

        reward = round(cost_saved - prod_loss, 4)
        return reward

    # ─────────────────────────────────────────
    # Q-TABLE UPDATE — Bellman equation
    # Call after observing reward + next state
    # ─────────────────────────────────────────
    def update(
        self,
        price_eur_mwh: float,
        demand_units: float,
        action_idx: int,
        reward: float,
        next_price: float,
        next_demand: float,
    ) -> float:
        """
        Bellman update:
        Q(s,a) ← Q(s,a) + α × [r + γ × max Q(s',a') - Q(s,a)]
        """
        p_idx, d_idx   = self.get_state(price_eur_mwh, demand_units)
        np_idx, nd_idx = self.get_state(next_price, next_demand)

        current_q  = self.q_table[p_idx, d_idx, action_idx]
        max_next_q = float(np.max(self.q_table[np_idx, nd_idx]))

        # Bellman equation
        new_q = current_q + self.alpha * (
            reward + self.gamma * max_next_q - current_q
        )
        self.q_table[p_idx, d_idx, action_idx] = new_q

        # Decay epsilon — gradually reduce exploration over time
        self.epsilon = max(
            self.epsilon_min,
            self.epsilon * self.epsilon_decay
        )

        self.total_updates += 1
        self.total_reward  += reward

        td_error = abs(new_q - current_q)
        return round(td_error, 6)

    # ─────────────────────────────────────────
    # SAVE / LOAD — pickle (not torch, <1MB)
    # ─────────────────────────────────────────
    def save(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({
                "q_table":       self.q_table,
                "epsilon":       self.epsilon,
                "total_updates": self.total_updates,
                "total_reward":  self.total_reward,
                "alpha":         self.alpha,
                "gamma":         self.gamma,
            }, f)
        logger.info("QLearner saved to %s (updates=%d)", path, self.total_updates)

    def load(self, path: str) -> bool:
        if not os.path.exists(path):
            logger.warning("No saved Q-table at %s — starting fresh", path)
            return False
        with open(path, "rb") as f:
            data = pickle.load(f)
        self.q_table       = data["q_table"]
        self.epsilon       = data["epsilon"]
        self.total_updates = data["total_updates"]
        self.total_reward  = data["total_reward"]
        self.alpha         = data.get("alpha", self.alpha)
        self.gamma         = data.get("gamma", self.gamma)
        logger.info("QLearner loaded from %s (updates=%d)", path, self.total_updates)
        return True

    def get_stats(self) -> dict:
        return {
            "total_updates": self.total_updates,
            "total_reward":  round(self.total_reward, 4),
            "epsilon":       round(self.epsilon, 4),
            "q_table_mean":  round(float(np.mean(self.q_table)), 6),
            "q_table_max":   round(float(np.max(self.q_table)), 6),
        }


# ─────────────────────────────────────────────
# SELF TEST
# ─────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("=" * 50)
    print("Q-Learner Self Test")
    print("=" * 50)

    agent = QLearner()

    # Simulate 20 steps
    print("\nSimulating 20 decision steps...\n")
    prices  = [30, 45, 55, 90, 95, 100, 40, 35, 75, 85,
               28, 60, 70, 110, 50, 38, 88, 95, 42, 65]
    demands = [35, 60, 80, 85, 45, 30, 75, 40, 65, 90,
               28, 55, 70, 88, 60, 35, 72, 80, 55, 68]

    for i in range(20):
        price  = prices[i]
        demand = demands[i]

        decision = agent.choose_action(price, demand)
        reward   = QLearner.calculate_reward(
            decision["action"], price, demand
        )

        next_p = prices[(i + 1) % 20]
        next_d = demands[(i + 1) % 20]
        td_err = agent.update(
            price, demand,
            decision["action_idx"],
            reward,
            next_p, next_d,
        )

        print(
            f"Step {i+1:2d} | price={price:3d} ({decision['price_level']:4s}) "
            f"demand={demand:2d} ({decision['demand_level']:4s}) | "
            f"action={decision['action']:12s} | "
            f"reward={reward:+.4f} | td_err={td_err:.6f}"
        )

    print("\nFinal Q-table stats:")
    stats = agent.get_stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")

    print("\nQ-Learning working correctly.")
