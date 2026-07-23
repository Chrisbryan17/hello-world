from jcc.native_build import native_build_jobs


def test_three_samples_create_nine_native_build_jobs() -> None:
    jobs = native_build_jobs(samples=3)
    assert len(jobs) == 9
    assert {job.variant_id for job in jobs} == {"20std", "40std", "40hc"}
    assert {job.progress for job in jobs} == {0.0, 0.5, 1.0}


def test_native_job_filenames_are_unique_and_fcstd() -> None:
    jobs = native_build_jobs(samples=5)
    filenames = [job.filename for job in jobs]
    assert len(filenames) == len(set(filenames))
    assert all(filename.endswith(".FCStd") for filename in filenames)
