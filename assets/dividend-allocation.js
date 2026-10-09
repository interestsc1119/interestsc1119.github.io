(function (root) {
    "use strict";

    function dateValue(value) {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(value || "")) return NaN;
        const day = Date.parse(value + "T00:00:00Z");
        return Number.isFinite(day) && new Date(day).toISOString().slice(0, 10) === value ? day : NaN;
    }

    function planAllocation(input) {
        const budget = Number(input.budget), invested = Number(input.invested);
        const percent = Number(input.percent), interval = Number(input.interval);
        const blocked = message => ({ state: "blocked", amount: 0, message });
        if (input.budget === "" || input.invested === "" || !Number.isFinite(budget) || !Number.isFinite(invested) || budget <= 0 || invested < 0 || invested > budget) {
            return blocked("请填写有效的专属总预算与累计已投入金额；已投入不得超过预算。这里不是你的全部资产。");
        }
        if (!Number.isFinite(percent) || percent <= 0 || percent > 100 || !Number.isFinite(interval) || interval < 1) {
            return blocked("预算规则无效，暂停计算。");
        }
        const budgetCents = Math.round(budget * 100), investedCents = Math.round(invested * 100);
        if (!Number.isSafeInteger(budgetCents) || !Number.isSafeInteger(investedCents) || budgetCents < 1) {
            return blocked("金额超出计算范围，暂停计算。");
        }
        const remaining = budgetCents - investedCents;
        if (remaining <= 0) return blocked("已达到你设定的专属总预算上限，不新增投入。");
        const today = dateValue(input.today);
        if (!Number.isFinite(today)) return blocked("当前日期无效，暂停计算。");
        if (invested > 0 && !input.lastBuy) return blocked("已有投入时，请填写最近一笔买入日期，避免每天重复加仓。");
        if (input.lastBuy) {
            const last = dateValue(input.lastBuy);
            if (!Number.isFinite(last) || last > today) return blocked("最近买入日期无效或在未来，暂停计算。");
            const days = Math.floor((today - last) / 86400000);
            if (days < interval) return blocked("距离上一笔仅 " + days + " 天；按示例规程还需等待 " + (interval - days) + " 天，不重复加仓。");
        }
        if (input.riskConfirmed !== true) return blocked("请先确认长期资金、回撤承受能力，以及分红和基金费用/溢价风险。");
        if (input.eligible !== true) return blocked("今日数据核验或配置条件尚未满足，不据此新增买入；不等于需要卖出已有持仓。");
        const amount = Math.min(Math.floor(budgetCents * percent / 100), remaining) / 100;
        if (amount < .01) return blocked("本笔预算不足一分钱，不新增投入。");
        return { state: "ready", amount, remaining: remaining / 100,
            message: "满足页面观察条件与手动预算检查。本笔预算上限为 " + amount.toFixed(2) + " 元，不是必须投入金额；实际成交还需核对ETF溢价、份额与交易费用。" };
    }

    if (typeof module !== "undefined" && module.exports) module.exports = { planAllocation, dateValue };
    if (!root || !root.document) return;
    root.DividendAllocation = { planAllocation };
    const form = root.document.getElementById("dividend-budget-form");
    if (!form) return;
    function todayHK() {
        const parts = new Intl.DateTimeFormat("en", { timeZone: "Asia/Hong_Kong", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
        const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
        return values.year + "-" + values.month + "-" + values.day;
    }
    form.addEventListener("submit", function (event) {
        event.preventDefault();
        const result = planAllocation({ budget: form.elements.budget.value, invested: form.elements.invested.value,
            lastBuy: form.elements.lastBuy.value, riskConfirmed: form.elements.riskConfirmed.checked,
            eligible: form.dataset.eligible === "true", percent: form.dataset.percent,
            interval: form.dataset.interval, today: todayHK() });
        root.document.getElementById("dividend-budget-result").textContent = result.message;
    });
})(typeof window !== "undefined" ? window : null);
