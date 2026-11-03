def test_package_metadata():
    import friday
    assert hasattr(friday, "__version__")
    assert friday.__version__ == "0.1.0"
