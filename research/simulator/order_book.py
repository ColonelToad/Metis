from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional
import heapq
import time

@dataclass
class Order:
    id: int
    side: str  # 'buy' or 'sell'
    type: str  # 'limit' or 'market'
    price: Optional[float]
    qty: float
    ts: float

@dataclass
class Trade:
    buy_id: int
    sell_id: int
    price: float
    qty: float
    ts: float

class PriceLevel:
    def __init__(self):
        self.queue: Deque[Order] = deque()

class OrderBook:
    def __init__(self, tick_size: float = 0.001):
        self.tick_size = tick_size
        self.bids: Dict[float, PriceLevel] = {}
        self.asks: Dict[float, PriceLevel] = {}
        self.bid_prices: List[float] = []  # max-heap (store negative)
        self.ask_prices: List[float] = []  # min-heap
        self.trades: List[Trade] = []
        self._next_id = 1

    def _normalize_price(self, p: float) -> float:
        return round(p / self.tick_size) * self.tick_size

    def _best_bid(self) -> Optional[float]:
        return -self.bid_prices[0] if self.bid_prices else None

    def _best_ask(self) -> Optional[float]:
        return self.ask_prices[0] if self.ask_prices else None

    def submit_limit(self, side: str, price: float, qty: float) -> int:
        order_id = self._next_id; self._next_id += 1
        price = self._normalize_price(price)
        ts = time.time()
        order = Order(order_id, side, 'limit', price, qty, ts)
        book = self.bids if side == 'buy' else self.asks
        heap = self.bid_prices if side == 'buy' else self.ask_prices
        key_price = price if side == 'sell' else -price

        if price not in book:
            book[price] = PriceLevel()
            heapq.heappush(heap, key_price)
        book[price].queue.append(order)
        self._match()
        return order_id

    def submit_market(self, side: str, qty: float) -> int:
        order_id = self._next_id; self._next_id += 1
        ts = time.time()
        order = Order(order_id, side, 'market', None, qty, ts)
        self._execute_market(order)
        return order_id

    def cancel(self, order_id: int) -> bool:
        # Simple linear search cancel
        for levels, heap, invert in [(self.bids, self.bid_prices, True), (self.asks, self.ask_prices, False)]:
            to_delete = []
            for price, level in levels.items():
                for i, o in enumerate(level.queue):
                    if o.id == order_id:
                        level.queue.remove(o)
                        if not level.queue:
                            to_delete.append(price)
                        return True
            for price in to_delete:
                del levels[price]
                key_price = (-price if invert else price)
                # rebuild heap
                if invert:
                    self.bid_prices = [-p for p in levels.keys()]
                    heapq.heapify(self.bid_prices)
                else:
                    self.ask_prices = [p for p in levels.keys()]
                    heapq.heapify(self.ask_prices)
        return False

    def _pop_best(self, side: str) -> Optional[Order]:
        if side == 'sell':
            if not self.ask_prices: return None
            best = self.ask_prices[0]
            level = self.asks[best]
            order = level.queue[0]
            return order
        else:
            if not self.bid_prices: return None
            best = -self.bid_prices[0]
            level = self.bids[best]
            order = level.queue[0]
            return order

    def _consume_best(self, side: str):
        if side == 'sell':
            best = self.ask_prices[0]
            level = self.asks[best]
            level.queue.popleft()
            if not level.queue:
                heapq.heappop(self.ask_prices)
                del self.asks[best]
        else:
            best = -self.bid_prices[0]
            level = self.bids[best]
            level.queue.popleft()
            if not level.queue:
                heapq.heappop(self.bid_prices)
                del self.bids[best]

    def _crossed(self) -> bool:
        bb = self._best_bid(); ba = self._best_ask()
        return bb is not None and ba is not None and bb >= ba

    def _match(self):
        while self._crossed():
            buy_order = self._pop_best('buy')
            sell_order = self._pop_best('sell')
            if not buy_order or not sell_order:
                break
            qty = min(buy_order.qty, sell_order.qty)
            price = sell_order.price  # price-time priority; trade at maker price
            ts = time.time()
            self.trades.append(Trade(buy_order.id, sell_order.id, price, qty, ts))
            buy_order.qty -= qty
            sell_order.qty -= qty
            if buy_order.qty <= 1e-12:
                self._consume_best('buy')
            if sell_order.qty <= 1e-12:
                self._consume_best('sell')

    def _execute_market(self, order: Order):
        side = order.side
        opp = 'sell' if side == 'buy' else 'buy'
        while order.qty > 1e-12:
            best = self._pop_best(opp)
            if not best:
                break
            qty = min(order.qty, best.qty)
            price = best.price
            ts = time.time()
            if side == 'buy':
                self.trades.append(Trade(order.id, best.id, price, qty, ts))
            else:
                self.trades.append(Trade(best.id, order.id, price, qty, ts))
            order.qty -= qty
            best.qty -= qty
            if best.qty <= 1e-12:
                self._consume_best(opp)

    def mid_price(self) -> Optional[float]:
        bb = self._best_bid(); ba = self._best_ask()
        if bb is None or ba is None: return None
        return (bb + ba) / 2

    def best_spread(self) -> Optional[float]:
        bb = self._best_bid(); ba = self._best_ask()
        if bb is None or ba is None: return None
        return max(0.0, ba - bb)

    def last_trade(self) -> Optional[Trade]:
        return self.trades[-1] if self.trades else None
