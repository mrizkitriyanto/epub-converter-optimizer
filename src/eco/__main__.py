import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from eco.cli import main

    raise SystemExit(main())
