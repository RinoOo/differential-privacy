//
// Copyright 2019 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
//

#ifndef DIFFERENTIAL_PRIVACY_ALGORITHMS_COUNT_H_
#define DIFFERENTIAL_PRIVACY_ALGORITHMS_COUNT_H_

#include "google/protobuf/any.pb.h"
#include "absl/status/status.h"
#include "base/statusor.h"
#include "algorithms/algorithm.h"
#include "algorithms/numerical-mechanisms.h"
#include "algorithms/util.h"
#include "proto/summary.pb.h"
#include "base/canonical_errors.h"
#include "base/status_macros.h"

namespace differential_privacy {

// Count the number of elements in a set, with differentially private noise.
template <typename T>
class Count : public Algorithm<T> {
 public:
  class Builder;

  void AddEntry(const T& v) override { AddMultipleEntries(v, 1); }

  base::StatusOr<ConfidenceInterval> NoiseConfidenceInterval(
      double confidence_level, double privacy_budget = 1) override {
    return mechanism_->NoiseConfidenceInterval(confidence_level,
                                               privacy_budget);
  }

  // Create and return summary containing the count.
  Summary Serialize() override {
    // Create CountSummary.
    CountSummary count_summ;
    count_summ.set_count(count_);

    // Create Summary.
    Summary summary;
    summary.mutable_data()->PackFrom(count_summ);
    return summary;
  }

  // Add count from serialized data.
  absl::Status Merge(const Summary& summary) override {
    if (!summary.has_data()) {
      return absl::InternalError("Cannot merge summary with no count data.");
    }

    // Add counts.
    CountSummary count_summary;
    if (!summary.data().UnpackTo(&count_summary)) {
      return absl::InternalError("Count summary unable to be unpacked.");
    }
    count_ += count_summary.count();

    return absl::OkStatus();
  }

  int64_t MemoryUsed() override {
    int64_t memory = sizeof(Count<T>);
    if (mechanism_) {
      memory += mechanism_->MemoryUsed();
    }
    return memory;
  }

 protected:
  base::StatusOr<Output> GenerateResult(double privacy_budget,
                                        double noise_interval_level) override {
    RETURN_IF_ERROR(ValidateIsPositive(privacy_budget, "Privacy budget",
                                       absl::StatusCode::kFailedPrecondition));

    Output output;
    int64_t countWithNoise;
    SafeCastFromDouble(std::round(mechanism_->AddNoise(count_, privacy_budget)),
                       countWithNoise);
    AddToOutput<int64_t>(&output, countWithNoise);

    base::StatusOr<ConfidenceInterval> interval =
        NoiseConfidenceInterval(noise_interval_level, privacy_budget);
    if (interval.ok()) {
      *(output.mutable_error_report()->mutable_noise_confidence_interval()) =
          interval.value();
    }
    return output;
  }

  void ResetState() override { count_ = 0; }

  uint64_t GetCount() const { return count_; }

  // The constructor and count_ are non-private for testing.
  Count(double epsilon, double delta, std::unique_ptr<NumericalMechanism> mechanism)
      : Algorithm<T>(epsilon, delta), count_(0), mechanism_(std::move(mechanism)) {}

 private:
  void AddMultipleEntries(const T& v, uint64_t num_of_entries) {
    count_ += num_of_entries;
  }

  // Friend class for testing only
  friend class CountTestPeer;

  uint64_t count_;
  std::unique_ptr<NumericalMechanism> mechanism_;
};

template <typename T>
class Count<T>::Builder
    : public AlgorithmBuilder<T, Count<T>, Count<T>::Builder> {
 private:
  using AlgorithmBuilder =
      differential_privacy::AlgorithmBuilder<T, Count<T>, Count<T>::Builder>;

  base::StatusOr<std::unique_ptr<Count<T>>> BuildAlgorithm() override {
    std::unique_ptr<NumericalMechanism> mechanism;
    ASSIGN_OR_RETURN(mechanism, AlgorithmBuilder::UpdateAndBuildMechanism());

    return absl::WrapUnique(new Count<T>(AlgorithmBuilder::GetEpsilon().value(),
                                         AlgorithmBuilder::GetDelta().value_or(0),
                                         std::move(mechanism)));
  }
};

}  // namespace differential_privacy

#endif  // DIFFERENTIAL_PRIVACY_ALGORITHMS_COUNT_H_
