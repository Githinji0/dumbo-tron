from brain_farm.app.evaluators.validator import FormulaValidator

def test_balanced_parentheses():
    assert FormulaValidator.validate_parentheses("rank(close)") is True
    assert FormulaValidator.validate_parentheses("group_neutralize(rank(close), subindustry)") is True
    assert FormulaValidator.validate_parentheses("group_neutralize(rank(close, subindustry") is False
    assert FormulaValidator.validate_parentheses("rank(close))") is False

def test_syntax_validation():
    allowed = ["close", "open", "volume", "vwap"]
    
    # Valid syntax
    ok, err = FormulaValidator.validate("rank(close)", allowed)
    assert ok is True
    
    # Unknown operator / field
    ok, err = FormulaValidator.validate("invalid_op(close)", allowed)
    assert ok is False
    assert "Unknown field or operator" in err
    
    # Valid window lookback limit checks
    ok, err = FormulaValidator.validate("ts_zscore(close, 20)", allowed)
    assert ok is True
    
    # Invalid window size values
    ok, err = FormulaValidator.validate("ts_zscore(close, 600)", allowed)
    assert ok is False
    assert "out of range" in err

    ok, err = FormulaValidator.validate("ts_zscore(close, 0)", allowed)
    assert ok is False
    
    # Nested Group Neutralization check
    ok, err = FormulaValidator.validate("group_neutralize(group_neutralize(rank(close), industry), subindustry)", allowed)
    assert ok is False
    assert "Nested 'group_neutralize'" in err
