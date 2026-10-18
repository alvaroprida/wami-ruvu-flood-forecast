# Run Wflow for each TOML given on the command line, in one Julia session
# so the package is compiled once for all ensemble members.
#
#   julia --project=pipeline/julia pipeline/julia/run_wflow.jl a.toml b.toml ...

using Wflow

for toml in ARGS
    @info "Wflow run" toml
    Wflow.run(toml)
end
