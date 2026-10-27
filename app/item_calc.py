"""
Shared item-calculation helpers for the Challan and Invoice screens.

One single place for the maths, so both screens always agree:

    Total Weight        = Weight per unit (kg)  x  Qty
    Amount (Qty-wise)   = Qty  x  Rate  +  Loading
    Amount (Kg-wise)    = Total Weight  x  Rate  +  Loading

Where the auto-fill values come from (Product Master):
    Rate     -> Wholesale Rate if entered, otherwise Price Per Unit, otherwise MRP Rate
    Loading  -> Loading (falls back to the old default_loading column)
    Qty      -> Quantity (1 if blank)
    Weight   -> Weight Kg (per unit)
    Unit / HSN -> Unit / HSN-SAC
"""

CALC_BY_OPTIONS = ['Qty', 'Kg']


def num(value, default=0.0):
    """Safe float: None / '' / '1,200.50' / bad text never raise."""
    try:
        text = str('' if value is None else value).strip().replace(',', '')
        return float(text) if text else default
    except (ValueError, TypeError):
        return default


def fnum(value):
    """Plain number for entry boxes / lists: 5.0 -> '5', 2.50 -> '2.5'."""
    text = f'{num(value):.6f}'.rstrip('0').rstrip('.')
    return text if text not in ('', '-0') else '0'


# ---------- values pulled from a Product Master row ----------
def product_rate(p):
    for key in ('wholesale_rate', 'price', 'mrp_rate'):
        v = num(p.get(key))
        if v > 0:
            return v
    return 0.0


def product_loading(p):
    v = num(p.get('loading'))
    return v if v > 0 else num(p.get('default_loading'))


def product_qty(p):
    q = num(p.get('qty'))
    return q if q > 0 else 1.0


# ---------- the calculation itself ----------
def calc_item(qty, rate, loading, weight_per_unit, calc_by='Qty'):
    total_weight = round(weight_per_unit * qty, 3)
    base = total_weight * rate if calc_by == 'Kg' else qty * rate
    return {
        'total_weight': total_weight,
        'base': round(base, 2),
        'amount': round(base + loading, 2),
    }


def formula_text(qty, rate, loading, weight_per_unit, calc_by='Qty'):
    """Human readable, step by step line shown live under the item fields."""
    c = calc_item(qty, rate, loading, weight_per_unit, calc_by)
    weight_step = f'Weight: {fnum(weight_per_unit)} kg x {fnum(qty)} = {fnum(c["total_weight"])} kg'
    if calc_by == 'Kg':
        amount_step = (f'Amount = {fnum(c["total_weight"])} kg x ₹{rate:,.2f}'
                       f' + Loading ₹{loading:,.2f} = ₹{c["amount"]:,.2f}')
    else:
        amount_step = (f'Amount = {fnum(qty)} x ₹{rate:,.2f}'
                       f' + Loading ₹{loading:,.2f} = ₹{c["amount"]:,.2f}')
    return f'{weight_step}     |     {amount_step}'


# ---------- helpers for editing a saved item ----------
def per_unit_weight(item):
    """Items store TOTAL weight (weight x qty); editing needs the per-unit value."""
    q = num(item.get('qty'))
    return num(item.get('weight_kg')) / q if q > 0 else 0.0


def infer_calc_by(item):
    """Tell whether a saved item was calculated Qty-wise or Kg-wise."""
    q = num(item.get('qty'))
    r = num(item.get('price'))
    l = num(item.get('loading'))
    tw = num(item.get('weight_kg'))
    amt = num(item.get('amount'))
    if tw > 0 and abs(amt - (tw * r + l)) < 0.01 and abs(amt - (q * r + l)) >= 0.01:
        return 'Kg'
    return 'Qty'
