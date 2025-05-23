#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Apr 18 13:46:38 2025


"""
import math
from typing import List

import numpy as np
from collections import deque

import json
from typing import Any

from datamodel import TradingState, Symbol, Order, Listing, OrderDepth, Trade, Observation, ProsperityEncoder

class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict[Symbol, list[Order]],
        conversions: int, trader_data: str) -> None:
        base_length = len(
            self.to_json(
                [
                    self.compress_state(state, ""),
                    self.compress_orders(orders),
                    conversions,
                    "",
                    "",
                ]
            )
        )

        # We truncate state.traderData, trader_data, and self.logs to the same max. length to fit the log limit
        max_item_length = (self.max_log_length - base_length) // 3

        print(
            self.to_json(
                [
                    self.compress_state(state, self.truncate(state.traderData, max_item_length)),
                    self.compress_orders(orders),
                    conversions,
                    self.truncate(trader_data, max_item_length),
                    self.truncate(self.logs, max_item_length),
                ]
            )
        )

        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [
            state.timestamp,
            trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            self.compress_trades(state.own_trades),
            self.compress_trades(state.market_trades),
            state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        compressed = []
        for listing in listings.values():
            compressed.append(
                [listing.symbol, listing.product, listing.denomination])

        return compressed

    def compress_order_depths(self, order_depths: dict[Symbol, OrderDepth]) -> dict[Symbol, list[Any]]:
        compressed = {}
        for symbol, order_depth in order_depths.items():
            compressed[symbol] = [order_depth.buy_orders,
                                  order_depth.sell_orders]

        return compressed

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        compressed = []
        for arr in trades.values():
            for trade in arr:
                compressed.append(
                    [
                        trade.symbol,
                        trade.price,
                        trade.quantity,
                        trade.buyer,
                        trade.seller,
                        trade.timestamp,
                    ]
                )

        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        for product, observation in observations.conversionObservations.items():
            conversion_observations[product] = [
                observation.bidPrice,
                observation.askPrice,
                observation.transportFees,
                observation.exportTariff,
                observation.importTariff,
                observation.sugarPrice,
                observation.sunlightIndex,
            ]

        return [observations.plainValueObservations, conversion_observations]

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        compressed = []
        for arr in orders.values():
            for order in arr:
                compressed.append([order.symbol, order.price, order.quantity])

        return compressed

    def to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        if len(value) <= max_length:
            return value

        return value[: max_length - 3] + "..."


logger = Logger()

class Trader:
    def __init__(self):
        # Position limits for all products
        self.limits = {
            "RAINFOREST_RESIN": 50,
            "KELP": 50,
            "SQUID_INK": 50,
            "CROISSANTS": 250,
            "JAMS": 350,
            "DJEMBES": 60,
            "PICNIC_BASKET1": 60,
            "PICNIC_BASKET2": 100,
            "VOLCANIC_ROCK": 400,
            'VOLCANIC_ROCK_VOUCHER_10000': 200,
            'VOLCANIC_ROCK_VOUCHER_10250': 200,
            'VOLCANIC_ROCK_VOUCHER_10500': 200,
        }

        # Histories
        self.squid_history: List[float] = []
        self.kelp_history: List[float] = []
        self.volcanic_rock_history: List[float] = []
        self.croissants_rock_history: List[float] = []

        # Momentum thresholds
        self.squid_momentum_threshold = 4.5
        self.kelp_momentum_threshold = 2

        # Strikes for Volcanic Rock Vouchers
        self.voucher_strikes = {
            "VOLCANIC_ROCK_VOUCHER_10000": 10000,
            "VOLCANIC_ROCK_VOUCHER_10250": 10250,
            "VOLCANIC_ROCK_VOUCHER_10500": 10500
        }


        # Defaults for the Black–Scholes logic
        self.default_vol = 0.3
        self.risk_free_rate = 0.0
        
        # Windows 
        self.rain_window = deque(maxlen=10)
        self.rain_window_size = 10
        self.kelp_window = deque(maxlen=10)
        self.croissants_window = deque(maxlen=10)
        
        # Specific volcanic information
        self.volcanic_stop_loss: float = 200.0
        self.volcanic_entry_price: float | None = None

    ############################################################################
    # Existing Strategies
    ############################################################################

    def RainforestResinStrategy(self, position: int, order_depth: OrderDepth) -> List[Order]:
        """
        Market‑making on RAINFOREST_RESIN around pivot=10_000,
        with window‑based soft/hard liquidations.
        """

        product = "RAINFOREST_RESIN"
        limit = self.limits[product]
        orders: List[Order] = []

        true_value = 10_000
        to_buy  = limit - position
        to_sell = limit + position

        self.rain_window.append(abs(position) == limit)
        if len(self.rain_window) > self.rain_window_size:
            self.rain_window.popleft()

        full        = len(self.rain_window) == self.rain_window_size
        soft_liq    = full and sum(self.rain_window) >= self.rain_window_size/2 and self.rain_window[-1]
        hard_liq    = full and all(self.rain_window)

        # Aggressive buys: any ask < pivot
        for price, vol in sorted(order_depth.sell_orders.items()):
            if price < true_value and to_buy > 0:
                qty = min(to_buy, abs(vol))
                orders.append(Order(product, price, qty))
                to_buy  -= qty
                position += qty

        # If still flat‑capped, liquidate towards pivot
        if to_buy > 0 and hard_liq:
            qty = to_buy // 2
            orders.append(Order(product, true_value, qty))
            to_buy -= qty
        if to_buy > 0 and soft_liq:
            qty = to_buy // 2
            orders.append(Order(product, true_value - 2, qty))
            to_buy -= qty

        # Fallback buy off the most popular bid
        if to_buy > 0 and order_depth.buy_orders:
            pop_bid = max(order_depth.buy_orders.items(), key=lambda x: x[1])[0]
            price   = min(true_value, pop_bid + 1)
            orders.append(Order(product, price, to_buy))
            to_buy = 0

        # Aggressive sells: any bid > pivot
        for price, vol in sorted(order_depth.buy_orders.items(), reverse=True):
            if price > true_value and to_sell > 0:
                qty = min(to_sell, vol)
                orders.append(Order(product, price, -qty))
                to_sell  -= qty
                position -= qty

        # If still limit‑stuck, liquidate towards pivot
        if to_sell > 0 and hard_liq:
            qty = to_sell // 2
            orders.append(Order(product, true_value, -qty))
            to_sell -= qty
        if to_sell > 0 and soft_liq:
            qty = to_sell // 2
            orders.append(Order(product, true_value + 2, -qty))
            to_sell -= qty

        # Fallback sell off the most popular ask
        if to_sell > 0 and order_depth.sell_orders:
            pop_ask = min(order_depth.sell_orders.items(), key=lambda x: x[1])[0]
            price   = max(true_value, pop_ask - 1)
            orders.append(Order(product, price, -to_sell))
            to_sell = 0

        return orders

    
    def KelpMMStrategy(self, position: int, order_depth: OrderDepth) -> List[Order]:
        """
        KELP market‑making with imbalance‑aware reservation
        """
        product = "KELP"
        limit = self.limits[product]
        orders: List[Order] = []
        QUOTE_SIZE = 10

        # Top‑of‑book midpoint and volume
        buys  = sorted(order_depth.buy_orders.items(),  reverse=True)
        sells = sorted(order_depth.sell_orders.items())
        if not buys or not sells:
            return orders
        best_bid, bid_vol = buys[0]
        best_ask, ask_vol = sells[0]
        mid = (best_bid + best_ask) / 2

        # Sliding‑window flags
        at_limit = abs(position) == limit
        self.kelp_window.append(at_limit)
        full     = len(self.kelp_window) == self.kelp_window.maxlen
        soft_liq = full and sum(self.kelp_window) >= self.kelp_window.maxlen/2 and self.kelp_window[-1]
        hard_liq = full and all(self.kelp_window)

        # Inventory skew (mild)
        skew = (position / limit) * 0.5
        res_price = mid - skew

        # Order‑book imbalance: shift price by (bid−ask)/(bid+ask)
        imbalance = (bid_vol - abs(ask_vol)) / (bid_vol + abs(ask_vol)) if (bid_vol + abs(ask_vol))>0 else 0
        imb_shift = imbalance * 1  # 1‑tick max shift
        res_price += imb_shift

        # Build quotes around res_price
        SPREAD = 2
        half = SPREAD / 2
        bid_px = int(round(res_price - half))
        ask_px = int(round(res_price + half))

        # Hard liquidation: single mid quote
        if hard_liq:
            size = min(limit - position, QUOTE_SIZE)
            if size > 0:
                orders.append(Order(product, int(mid), size))
            size = min(limit + position, QUOTE_SIZE)
            if size > 0:
                orders.append(Order(product, int(mid), -size))
            return orders

        # Soft liquidation: widen spread
        if soft_liq:
            bid_px -= 1
            ask_px += 1

        # Post buy-side quote (improve best_bid)
        if position < limit and bid_px > best_bid:
            size = min(limit - position, QUOTE_SIZE, abs(ask_vol))
            if size > 0:
                orders.append(Order(product, bid_px, size))

        # Post sell-side quote (improve best_ask)
        if position > -limit and ask_px < best_ask:
            size = min(limit + position, QUOTE_SIZE, bid_vol)
            if size > 0:
                orders.append(Order(product, ask_px, -size))

        return orders

    
    def SquidInkStrategy(self, position: int, order_depth: OrderDepth) -> List[Order]:
        """
        Fixed‑mean mean‑reversion on SQUID_INK with momentum filter:
        Only trade when mid moves ≥0 ticks toward the mean
        """
        product = "SQUID_INK"
        limit   = self.limits[product]
        orders: List[Order] = []

        # Ensure both sides of book exist
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders

        # Top‑of‑book bid & ask, compute mid
        best_bid, bid_vol = max(order_depth.buy_orders.items(), key=lambda x: x[0])
        best_ask, ask_vol = min(order_depth.sell_orders.items(), key=lambda x: x[0])
        mid = (best_bid + best_ask) / 2

        # Grab previous mid (if any) to measure momentum
        prev = self.squid_history[-1] if self.squid_history else None

        # Append current mid to history (cap at 100)
        self.squid_history.append(mid)
        if len(self.squid_history) > 100:
            self.squid_history = self.squid_history[-100:]

        # 5) Fixed pivot, threshold, and required momentum
        MEAN      = 1900
        THRESHOLD = 50
        MOM_MOVE  = 1

        # Buy signal: mid < MEAN−THRESHOLD and has risen ≥ MOM_MOVE
        if prev is not None and mid < MEAN - THRESHOLD and (mid - prev) >= MOM_MOVE:
            qty = min(limit - position, abs(ask_vol))
            if qty > 0:
                orders.append(Order(product, best_ask, qty))

        # Sell signal: mid > MEAN+THRESHOLD and has fallen ≥ MOM_MOVE
        elif prev is not None and mid > MEAN + THRESHOLD and (prev - mid) >= MOM_MOVE:
            qty = min(limit + position, bid_vol)
            if qty > 0:
                orders.append(Order(product, best_bid, -qty))

        return orders

    
    def VolcanicRockStrategy(self, position: int, tradingState: TradingState) -> List[Order]:
        """
        Volcanic Rock momentum:
        z‑score = (mid – mid_L) / std(last 5 tick moves)
        ENTRY_Z threshold to trigger
        """
        product = "VOLCANIC_ROCK"
        limit   = self.limits[product]
        orders: List[Order] = []

        order_depth = tradingState.order_depths.get(product)
        if not order_depth or not order_depth.buy_orders or not order_depth.sell_orders:
            return orders

        # Top‑of‑book
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        mid      = 0.5 * (best_bid + best_ask)

        # Record mid in history
        self.volcanic_rock_history.append(mid)
        MAX_HISTORY = 100
        if len(self.volcanic_rock_history) > MAX_HISTORY:
            self.volcanic_rock_history.pop(0)

        # Need at least L+1 points to compute L returns
        L = 3
        if len(self.volcanic_rock_history) <= L:
            return orders

        # Compute return over L ticks
        mid_L = self.volcanic_rock_history[-L-1]   # L ticks ago
        ret   = mid - mid_L

        # Compute σ = stdev of last L tick moves
        hist = self.volcanic_rock_history[-(L+1):]  # last L+1 mids
        moves = [hist[i] - hist[i-1] for i in range(1, len(hist))]
        σ     = np.std(moves) if moves else 1.0

        # z‑score
        z = ret / (σ if σ else 1.0)

        # Entry thresholds
        ENTRY_Z = 4

        # Long momentum: strong positive z
        if z > ENTRY_Z:
            qty = min(limit - position, order_depth.sell_orders[best_ask])
            if qty > 0:
                orders.append(Order(product, best_ask, qty))

        # Short momentum: strong negative z
        elif z < -ENTRY_Z:
            qty = min(limit + position, order_depth.buy_orders[best_bid])
            if qty > 0:
                orders.append(Order(product, best_bid, -qty))

        return orders

    ############################################################################
    # Simple Range Strategies for Croissants, Jams, Djembes (if you want them)
    ############################################################################

    def CroissantsMMStrategy(self, position: int, order_depth: OrderDepth) -> List[Order]:
        
        """
        Croissant market‑making with imbalance‑aware reservation
        """
        product = "CROISSANTS"
        limit = self.limits[product]
        orders: List[Order] = []
        QUOTE_SIZE = 10

        # Top‑of‑book midpoint and volume
        buys  = sorted(order_depth.buy_orders.items(),  reverse=True)
        sells = sorted(order_depth.sell_orders.items())
        if not buys or not sells:
            return orders
        best_bid, bid_vol = buys[0]
        best_ask, ask_vol = sells[0]
        mid = (best_bid + best_ask) / 2

        # Sliding‑window flags
        at_limit = abs(position) == limit
        self.croissants_window.append(at_limit)
        full     = len(self.croissants_window) == self.croissants_window.maxlen
        soft_liq = full and sum(self.croissants_window) >= self.croissants_window.maxlen/2 and self.croissants_window[-1]
        hard_liq = full and all(self.croissants_window)

        # Inventory skew (mild)
        skew = (position / limit) * 0.5
        res_price = mid - skew

        # Order‑book imbalance: shift price by (bid−ask)/(bid+ask)
        imbalance = (bid_vol - abs(ask_vol)) / (bid_vol + abs(ask_vol)) if (bid_vol + abs(ask_vol))>0 else 0
        imb_shift = imbalance * 1  # 1‑tick max shift
        res_price += imb_shift

        # Build quotes around res_price
        SPREAD = 2
        half = SPREAD / 2
        bid_px = int(round(res_price - half))
        ask_px = int(round(res_price + half))

        # Hard liquidation: single mid quote
        if hard_liq:
            size = min(limit - position, QUOTE_SIZE)
            if size > 0:
                orders.append(Order(product, int(mid), size))
            size = min(limit + position, QUOTE_SIZE)
            if size > 0:
                orders.append(Order(product, int(mid), -size))
            return orders

        # Soft liquidation: widen spread
        if soft_liq:
            bid_px -= 1
            ask_px += 1

        # Post buy-side quote (improve best_bid)
        if position < limit and bid_px >= best_bid:
            size = min(limit - position, QUOTE_SIZE, abs(ask_vol))
            if size > 0:
                orders.append(Order(product, bid_px, size))

        # Post sell-side quote (improve best_ask)
        if position > -limit and ask_px <= best_ask:
            size = min(limit + position, QUOTE_SIZE, bid_vol)
            if size > 0:
                orders.append(Order(product, ask_px, -size))

        return orders

    def JamsStrategy(self, position: int, order_depth: OrderDepth) -> List[Order]:
        """
        Jams floor/ceiling based strategy
        """
        product = "JAMS"
        floor_price = 6445
        ceiling_price = 6460
        limit = self.limits[product]
        orders: List[Order] = []

        if order_depth.sell_orders:
            best_ask = min(order_depth.sell_orders.keys())
            best_ask_vol = order_depth.sell_orders[best_ask]
            if best_ask <= floor_price + 1:
                can_buy = limit - position
                qty_to_buy = min(can_buy, abs(best_ask_vol))
                if qty_to_buy > 0:
                    orders.append(Order(product, best_ask, qty_to_buy))

        if order_depth.buy_orders:
            best_bid = max(order_depth.buy_orders.keys())
            best_bid_vol = order_depth.buy_orders[best_bid]
            if best_bid >= ceiling_price - 1:
                can_sell = limit + position
                qty_to_sell = min(can_sell, best_bid_vol)
                if qty_to_sell > 0:
                    orders.append(Order(product, best_bid, -qty_to_sell))

        return orders

    def DjembesStrategy(self, position: int, order_depth: OrderDepth) -> List[Order]:
        """
        Djembes floor/ceiling based strategy
        """
        product = "DJEMBES"
        floor_price = 13345
        ceiling_price = 13400
        limit = self.limits[product]
        orders: List[Order] = []

        if order_depth.sell_orders:
            best_ask = min(order_depth.sell_orders.keys())
            best_ask_vol = order_depth.sell_orders[best_ask]
            if best_ask <= floor_price + 1:
                can_buy = limit - position
                qty_to_buy = min(can_buy, abs(best_ask_vol))
                if qty_to_buy > 0:
                    orders.append(Order(product, best_ask, qty_to_buy))

        if order_depth.buy_orders:
            best_bid = max(order_depth.buy_orders.keys())
            best_bid_vol = order_depth.buy_orders[best_bid]
            if best_bid >= ceiling_price - 1:
                can_sell = limit + position
                qty_to_sell = min(can_sell, best_bid_vol)
                if qty_to_sell > 0:
                    orders.append(Order(product, best_bid, -qty_to_sell))

        return orders

    ############################################################################
    # Picnic Basket Arbitrage
    ############################################################################

    def PicnicBasket1ArbStrategy(self, position_basket: int, tradingState: TradingState) -> List[Order]:
        """
        Picnic Basket 1 = 6 CROISSANTS + 3 JAMS + 1 DJEMBES
        Arbitrage conditions:
          1) If best_ask_basket1 < 6*best_bid_croissants + 3*best_bid_jams + 1*best_bid_djembes,
             buy basket, sell constituents
          2) If best_bid_basket1 > 6*best_ask_croissants + 3*best_ask_jams + 1*best_ask_djembes,
             buy constituents, sell basket
        Ignores volumes for brevity; you may incorporate them to limit order sizes.
        """
        product = "PICNIC_BASKET1"
        orders: List[Order] = []
        limit_basket = self.limits[product]

        # Gather each relevant order depth
        depth_basket = tradingState.order_depths.get("PICNIC_BASKET1")
        depth_croissants = tradingState.order_depths.get("CROISSANTS")
        depth_jams = tradingState.order_depths.get("JAMS")
        depth_djembes = tradingState.order_depths.get("DJEMBES")

        # Ensure we have all the required order books
        if not (
            depth_basket and depth_croissants and depth_jams and depth_djembes):
            return orders

        # Helper: best ask & best bid for each item
        def best_ask(depth: OrderDepth):
            return min(depth.sell_orders.keys()) if depth.sell_orders else None

        def best_bid(depth: OrderDepth):
            return max(depth.buy_orders.keys()) if depth.buy_orders else None

        ask_basket = best_ask(depth_basket)
        bid_basket = best_bid(depth_basket)
        ask_croissants = best_ask(depth_croissants)
        bid_croissants = best_bid(depth_croissants)
        ask_jams = best_ask(depth_jams)
        bid_jams = best_bid(depth_jams)
        ask_djembes = best_ask(depth_djembes)
        bid_djembes = best_bid(depth_djembes)

        # Check we have valid prices
        if not (
            ask_basket and bid_basket and ask_croissants and bid_croissants and
            ask_jams and bid_jams and ask_djembes and bid_djembes):
            return orders

        # Calculate the sum of the constituents (for 1 unit of basket)
        # Sell constituents = use best BID for each
        basket_contents_bid_value = 6 * bid_croissants + 3 * bid_jams + 1 * bid_djembes
        # Buy constituents = use best ASK for each
        basket_contents_ask_value = 6 * ask_croissants + 3 * ask_jams + 1 * ask_djembes

        # Buy the basket at ask, sell the constituents at their bids
        # if ask_basket < sum of constituent bids
        if ask_basket < basket_contents_bid_value:
            # We'll do 1 basket for simplicity (or you could do multiple)
            can_buy_basket = limit_basket - position_basket
            if can_buy_basket > 0:
                # Place an order to buy +1 basket
                ask_volume_basket = depth_basket.sell_orders[ask_basket]
                qty_basket = min(can_buy_basket, abs(ask_volume_basket))
                if qty_basket > 0:
                    orders.append(Order(product, ask_basket, qty_basket))
                # You would also place SELL orders on the constituents
                # (CROISSANTS, JAMS, DJEMBES) if you want to realize the arb
                # Example (selling 6 CROISSANTS * qty_basket):
                # This requires you to track positions in CROISSANTS, etc.
                # For brevity we omit those orders. You can incorporate them
                # if your environment supports multi-product trades.

        # Buy the constituents at ask, sell the basket at bid
        # if bid_basket > sum of constituent asks
        if bid_basket > basket_contents_ask_value:
            # We'll do 1 basket for simplicity
            can_sell_basket = self.limits["PICNIC_BASKET1"] + position_basket
            if can_sell_basket > 0:
                bid_volume_basket = depth_basket.buy_orders[bid_basket]
                qty_basket = min(can_sell_basket, bid_volume_basket)
                if qty_basket > 0:
                    # Place an order to SELL the basket
                    orders.append(Order(product, bid_basket, -qty_basket))
                # Similarly, you'd place BUY orders for the constituents
                # (6 CROISSANTS, 3 JAMS, 1 DJEMBES). Omitted for brevity.

        return orders

    def PicnicBasket2ArbStrategy(self, position_basket: int, tradingState: TradingState) -> List[Order]:
        """
        Picnic Basket 2 = 4 CROISSANTS + 2 JAMS
        Similar arbitrage concept:
          1) If best_ask_basket2 < 4*best_bid_croissants + 2*best_bid_jams => buy basket, sell croissants+jams
          2) If best_bid_basket2 > 4*best_ask_croissants + 2*best_ask_jams => buy croissants+jams, sell basket
        """
        product = "PICNIC_BASKET2"
        orders: List[Order] = []
        limit_basket = self.limits[product]

        depth_basket = tradingState.order_depths.get("PICNIC_BASKET2")
        depth_croissants = tradingState.order_depths.get("CROISSANTS")
        depth_jams = tradingState.order_depths.get("JAMS")

        if not (depth_basket and depth_croissants and depth_jams):
            return orders

        def best_ask(depth: OrderDepth):
            return min(depth.sell_orders.keys()) if depth.sell_orders else None

        def best_bid(depth: OrderDepth):
            return max(depth.buy_orders.keys()) if depth.buy_orders else None

        ask_basket = best_ask(depth_basket)
        bid_basket = best_bid(depth_basket)
        ask_croissants = best_ask(depth_croissants)
        bid_croissants = best_bid(depth_croissants)
        ask_jams = best_ask(depth_jams)
        bid_jams = best_bid(depth_jams)

        if not (
            ask_basket and bid_basket and ask_croissants and bid_croissants and ask_jams and bid_jams):
            return orders

        basket_contents_bid_value = 4 * bid_croissants + 2 * bid_jams
        basket_contents_ask_value = 4 * ask_croissants + 2 * ask_jams

        # Buy basket at ask, sell constituents
        if ask_basket < basket_contents_bid_value:
            can_buy_basket = limit_basket - position_basket
            if can_buy_basket > 0:
                ask_volume_basket = depth_basket.sell_orders[ask_basket]
                qty_basket = min(can_buy_basket, abs(ask_volume_basket))
                if qty_basket > 0:
                    orders.append(Order(product, ask_basket, qty_basket))
                # Omit SELL orders for croissants/jams for brevity

        # Buy constituents, sell basket at bid
        if bid_basket > basket_contents_ask_value:
            can_sell_basket = limit_basket + position_basket
            if can_sell_basket > 0:
                bid_volume_basket = depth_basket.buy_orders[bid_basket]
                qty_basket = min(can_sell_basket, bid_volume_basket)
                if qty_basket > 0:
                    orders.append(Order(product, bid_basket, -qty_basket))
                # Omit BUY orders for croissants/jams for brevity

        return orders

    ############################################################################
    # Options Strategies
    ############################################################################

    def compute_time_to_expiry(self, day: int, timestamp: int) -> float:
        """
        Example function to compute T in years from day + microseconds.
        If the final expiry is at day=7, this is just an example approach.
        """
        microseconds_remaining = (7 - day) * 1_000_000 - timestamp
        if microseconds_remaining <= 0:
            return 0.0

        # Assume 1M microseconds ~ 1 trading day, 252 trading days ~ 1 year
        return microseconds_remaining / (252.0 * 1_000_000)

    def compute_realized_volatility(self, prices: List[float], min_points: int = 10) -> float:
        """
        Computes an annualized realized volatility from log returns
        in the given price history. Must have >= min_points data.
        Example: multiply stdev of log returns by sqrt(252).
        """
        if len(prices) < min_points:
            return self.default_vol  # fallback

        returns = []
        for i in range(1, len(prices)):
            if prices[i] > 0 and prices[i - 1] > 0:
                r = math.log(prices[i] / prices[i - 1])
                returns.append(r)

        if not returns:
            return self.default_vol

        stdev = np.std(returns)
        realized_vol = stdev * math.sqrt(252)

        # Optionally clamp extremes so it doesn't blow up or go too low
        realized_vol = max(min(realized_vol, 2.0), 0.01)
        return realized_vol

    # --------------------------------------------------------------------------
    # 2) Parabolic Smoother
    # --------------------------------------------------------------------------
    def parabolic_smoother(self, prices: List[float]) -> float:
        """
        Fits a degree-2 polynomial (a parabola) to 'prices'
        and returns the predicted value at the final point.
        """
        N = len(prices)
        if N < 3:
            return prices[-1]

        x = np.arange(N)
        y = np.array(prices)
        coeffs = np.polyfit(x, y, 2)
        smoothed_value = np.polyval(coeffs, N - 1)
        return smoothed_value

    def normal_cdf(self, x: float) -> float:
        """
        Returns the standard normal cumulative distribution function Phi(x),
        computed via math.erf for a no-scipy environment.
        """
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    # --------------------------------------------------------------------------
    # 3) Black–Scholes
    # --------------------------------------------------------------------------
    def black_scholes_price(self,option_type: str,underlying_price: float,strike_price: float,
    volatility: float,risk_free_rate: float,time_to_expiry: float) -> float:
        if (
            underlying_price <= 0
            or strike_price <= 0
            or time_to_expiry <= 0
            or volatility <= 0
        ):
            return float('nan')

        try:
            d1 = (math.log(underlying_price / strike_price)+ (risk_free_rate + 0.5 * volatility ** 2)
                     * time_to_expiry) / (volatility * math.sqrt(time_to_expiry))
            d2 = d1 - volatility * math.sqrt(time_to_expiry)
        except (ValueError, OverflowError):
            return float('nan')

        if option_type.lower() == 'call':
            return (underlying_price * self.normal_cdf(d1)
                - strike_price * math.exp(
                -risk_free_rate * time_to_expiry) * self.normal_cdf(d2))
        elif option_type.lower() == 'put':
            return (strike_price * math.exp(-risk_free_rate * time_to_expiry) * math.norm.cdf(-d2)
                    - underlying_price * self.normal_cdf(-d1))
        else:
            return float('nan')

    # --------------------------------------------------------------------------
    # 4) The “Volcanic Rock Vouchers” Strategy Updated for Rolling Vol
    # --------------------------------------------------------------------------
    def volcanicRockVouchersStrategy(self,product: str, position: int, tradingState: TradingState) -> List[Order]:
        orders: List[Order] = []

        depth_rock = tradingState.order_depths.get("VOLCANIC_ROCK", None)
        if not depth_rock or not depth_rock.buy_orders or not depth_rock.sell_orders:
            return orders

        # Compute raw underlying mid
        best_bid_rock = max(depth_rock.buy_orders.keys())
        best_ask_rock = min(depth_rock.sell_orders.keys())
        raw_underlying_mid = 0.5 * (best_bid_rock + best_ask_rock)

        # Update rolling history of underlying
        self.volcanic_rock_history.append(raw_underlying_mid)
        threshold_history = 1000
        if len(self.volcanic_rock_history) > threshold_history :
            self.volcanic_rock_history = self.volcanic_rock_history[-threshold_history:]

        if len(self.volcanic_rock_history) < 2:
            return orders  # Not enough data to do anything yet

        # Compute realized volatility from the last 50 data points (or fewer)
        dyn_vol = self.compute_realized_volatility(self.volcanic_rock_history,
                                                   min_points=10)

        # Optionally smooth the underlying mid price
        if len(self.volcanic_rock_history) >= 3:
            smoothed_underlying = self.parabolic_smoother(
                self.volcanic_rock_history)
        else:
            smoothed_underlying = raw_underlying_mid

        # Compute T
        day = getattr(tradingState, "day", 0)
        T = self.compute_time_to_expiry(day, tradingState.timestamp)
        if T <= 0:
            return orders

        # Strike => Black–Scholes with dynamic vol & smoothed price
        strike = self.voucher_strikes[product]
        black_scholes_price = self.black_scholes_price(
            option_type='call',
            underlying_price=smoothed_underlying,
            strike_price=strike,
            volatility=dyn_vol,  # <--- updated volatility from history
            risk_free_rate=self.risk_free_rate,
            time_to_expiry=T
        )

        # Compare fair_call vs. best bid/ask in the voucher
        depth_voucher = tradingState.order_depths.get(product, None)
        if not depth_voucher or not depth_voucher.buy_orders or not depth_voucher.sell_orders:
            return orders

        best_bid_voucher = max(depth_voucher.buy_orders.keys())
        best_ask_voucher = min(depth_voucher.sell_orders.keys())
        limit_pos = self.limits.get(product, 50)

        threshold = 5.0
        buy_edge = black_scholes_price - best_ask_voucher
        if buy_edge >= threshold:
            can_buy = limit_pos - position
            ask_vol = abs(depth_voucher.sell_orders[best_ask_voucher])
            qty = min(can_buy, ask_vol)
            if qty > 0:
                orders.append(Order(product, best_ask_voucher, qty))

        sell_edge = best_bid_voucher - black_scholes_price
        if sell_edge >= threshold:
            can_sell = limit_pos + position
            bid_vol = depth_voucher.buy_orders[best_bid_voucher]
            qty = min(can_sell, bid_vol)
            if qty > 0:
                orders.append(Order(product, best_bid_voucher, -qty))

        return orders

    ############################################################################
    # Logging
    ############################################################################

    def printTradingState(self, tradingState: TradingState):
        print(f"--- Trading State at timestamp {tradingState.timestamp} ---")
        print(f"Trader Data: {tradingState.traderData}")

        print("Positions:")
        for product, pos in tradingState.position.items():
            print(f"  {product}: {pos}")

        print("\nOrder Depths:")
        for symbol, depth in tradingState.order_depths.items():
            print(f"  Symbol: {symbol}")
            print(f"    Buy Orders:  {depth.buy_orders}")
            print(f"    Sell Orders: {depth.sell_orders}")

        print("\nOwn Trades Since Last Update:")
        for symbol, trades in tradingState.own_trades.items():
            if trades:
                print(f"  {symbol}: {trades}")

        print("\nMarket Trades Since Last Update:")
        for symbol, trades in tradingState.market_trades.items():
            if trades:
                print(f"  {symbol}: {trades}")

        print("\nObservations:")
        print(tradingState.observations)
        print("--- End of Trading State ---\n")
        return None

    ############################################################################
    # Main run / Orchestration
    ############################################################################

    def process_product(self, result, product, tradingState: TradingState) -> List[Order]:
        """
        Decide how to trade each product.
        We'll call the existing or new strategies as appropriate.
        For Picnic Baskets, use the arb strategies.
        """
        position = tradingState.position.get(product, 0)
        order_depth: OrderDepth = tradingState.order_depths[product]
        orders: List[Order] = []

        if product == "RAINFOREST_RESIN":
            orders = self.RainforestResinStrategy(position, order_depth)
        #
        elif product == "SQUID_INK":
            orders = self.SquidInkStrategy(position, order_depth)
        #
        elif product == "KELP":
            orders = self.KelpMMStrategy(position, order_depth)
        #
        elif product == "CROISSANTS":
            orders = self.CroissantsMMStrategy(position, order_depth)
        #
        elif product == "JAMS":
             orders = self.JamsStrategy(position, order_depth)
        #
        elif product == "DJEMBES":
            orders = self.DjembesStrategy(position, order_depth)
            
        elif product == "PICNIC_BASKET1":
            orders = self.PicnicBasket1ArbStrategy(position, tradingState)
        #
        elif product == "PICNIC_BASKET2":   
            orders = self.PicnicBasket2ArbStrategy(position, tradingState)
            
        elif product == "VOLCANIC_ROCK":
            orders = self.VolcanicRockStrategy(position, tradingState)

        if product in self.voucher_strikes:
            orders = self.volcanicRockVouchersStrategy(product, position, tradingState)

        return orders

    def run(self, state: TradingState) -> tuple[
        dict[Symbol, List[Order]], int, str]:
        """
        1) For each product in state.order_depths, decide how to trade.
        2) Return (dict of symbol->List[Order], conversions used, updated traderData).
        """
        print(f"traderData: {state.traderData}")
        print(f"Observations: {state.observations}")

        result = {}
        for product in state.order_depths:
            result[product] = self.process_product(result, product, state)

        conversions = 0
        traderData = ""

        logger.flush(state, result, conversions, traderData)

        return (result, conversions, traderData)
