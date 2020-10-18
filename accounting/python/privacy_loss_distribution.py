# Copyright 2020 Google LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Implementing Privacy Loss Distribution.

This file implements the privacy loss distribution (PLD) and its basic
functionalities. The main feature of PLD is that it allows for accurate
computation of privacy parameters under composition. Please refer to the
supplementary material below for more details:
../docs/Privacy_Loss_Distributions.pdf
"""

import abc
import collections
import math
import typing
import dataclasses
import numpy
from scipy import signal
from scipy import stats


def dictionary_to_list(
    input_dictionary: typing.Mapping[int, float]
) -> typing.Tuple[int, typing.List[float]]:
  """Converts an integer-keyed dictionary into an list.

  Args:
    input_dictionary: A dictionary whose keys are integers.

  Returns:
    A tuple of an integer offset and a list result_list. The offset is the
    minimum value of the input dictionary. result_list has length equal to the
    difference between the maximum and minimum values of the input dictionary.
    result_list[i] is equal to dictionary[offset + i] and is zero if offset + i
    is not a key in the input dictionary.
  """
  offset = min(input_dictionary)
  max_val = max(input_dictionary)
  result_list = [input_dictionary.get(i, 0) for i in range(offset, max_val + 1)]
  return (offset, result_list)


def list_to_dictionary(input_list: typing.List[float],
                       offset: int) -> typing.Mapping[int, float]:
  """Converts a list into an integer-key dictionary, with a specified offset.

  Args:
    input_list: An input list.
    offset: The offset in the key of the output dictionary

  Returns:
    A dictionary whose value at key is equal to input_list[key - offset]. If
    input_list[key - offset] is less than or equal to zero, it is not included
    in the dictionary.
  """
  result_dictionary = {}
  for i in range(len(input_list)):
    if input_list[i] > 0:
      result_dictionary[i + offset] = input_list[i]
  return result_dictionary


def convolve_dictionary(
    dictionary1: typing.Mapping[int, float],
    dictionary2: typing.Mapping[int, float]) -> typing.Mapping[int, float]:
  """Computes a convolution of two dictionaries.

  Args:
    dictionary1: The first dictionary whose keys are integers.
    dictionary2: The second dictionary whose keys are integers.

  Returns:
    The dictionary where for each key its corresponding value is the sum, over
    all key1, key2 such that key1 + key2 = key, of dictionary1[key1] times
    dictionary2[key2]
  """

  # Convert the dictionaries to lists.
  min1, list1 = dictionary_to_list(dictionary1)
  min2, list2 = dictionary_to_list(dictionary2)

  # Compute the convolution of the two lists.
  result_list = signal.fftconvolve(list1, list2)

  # Convert the list back to a dictionary and return
  return list_to_dictionary(result_list, min1 + min2)


def self_convolve_dictionary(input_dictionary: typing.Mapping[int, float],
                             num_times: int):
  """Computes a convolution of the input dictionary with itself num_times times.

  Args:
    input_dictionary: The input dictionary whose keys are integers.
    num_times: The number of times the dictionary is to be convolved with
      itself.

  Returns:
    The dictionary where for each key its corresponding value is the sum, over
    all key1, key2, ..., key_num_times such that key1 + key2 + ... +
    key_num_times = key, of input_dictionary[key1] * input_dictionary[key2] *
    ... * input_dictionary[key_num_times]
  """

  # Convert the dictionary to list.
  min_val, input_list = dictionary_to_list(input_dictionary)

  # Use FFT to compute the convolution
  result_list = numpy.fft.ifft(
      numpy.fft.fft(input_list, num_times * len(input_list))**num_times)

  # Get rid of complex part of the results in the list
  result_list_real_part = [numpy.real(i) for i in result_list]

  # Convert the list back to a dictionary and return
  return list_to_dictionary(result_list_real_part, min_val * num_times)


@dataclasses.dataclass
class DifferentialPrivacyParameters(object):
  """Representation of the differential privacy parameters of a mechanism.

  Attributes:
    epsilon: the epsilon in (epsilon, delta)-differential privacy.
    delta: the delta in (epsilon, delta)-differential privacy.
  """
  epsilon: float
  delta: float = 0


class PrivacyLossDistribution(object):
  """Class for privacy loss distributions and computation involving them.

  The privacy loss distribution (PLD) of two discrete distributions, the upper
  distribution mu_upper and the lower distribution mu_lower, is defined as a
  distribution on real numbers generated by first sampling an outcome o
  according to mu_upper and then outputting the privacy loss
  ln(mu_upper(o) / mu_lower(o)) where mu_lower(o) and mu_upper(o) are the
  probability masses of o in mu_lower and mu_upper respectively. This class
  allows one to create and manipulate privacy loss distributions.

  PLD allows one to (approximately) compute the epsilon-hockey stick divergence
  between mu_upper and mu_lower, which is defined as
  sum_{o} [mu_upper(o) - e^{epsilon} * mu_lower(o)]_+. This quantity in turn
  governs the parameter delta of (eps, delta)-differential privacy of the
  corresponding protocol. (See Observation 1 in the supplementary material.)

  The above definitions extend to continuous distributions. The PLD of two
  continuous distributions mu_upper and mu_lower is defined as a distribution on
  real numbers generated by first sampling an outcome o according to mu_upper
  and then outputting the privacy loss ln(f_{mu_upper}(o) / f_{mu_lower}(o))
  where f_{mu_lower}(o) and f_{mu_upper}(o) are the probability density
  functions at o in mu_lower and mu_upper respectively. Moreover, for continuous
  distributions the epsilon-hockey stick divergence is defined as
  integral [f_{mu_upper}(o) - e^{epsilon} * f_{mu_lower}(o)]_+ do.

  Attributes:
    value_discretization_interval: the interval length for which the values of
      the privacy loss distribution are discretized. In particular, the values
      are always integer multiples of value_discretization_interval.
    rounded_probability_mass_function: the probability mass function for the
      privacy loss distribution where each value is rounded to be an integer
      multiple of value_discretization_interval. To avoid floating point errors
      in the values, the keys here are the integer multipliers. For example,
      suppose that the probability mass function assigns mass of 0.1 to the
      value 2 * value_discretization_interval, then the dictionary will have
      (key: value) pair (2: 0.1).
    infinity_mass: The probability mass of mu_upper over all the outcomes that
      can occur only in mu_upper but not in mu_lower.(These outcomes result in
      privacy loss ln(mu_upper(o) / mu_lower(o)) of infinity.)
  """

  def __init__(self,
               rounded_probability_mass_function: typing.Mapping[int, float],
               value_discretization_interval: float,
               infinity_mass: float):
    self.rounded_probability_mass_function = rounded_probability_mass_function
    self.value_discretization_interval = value_discretization_interval
    self.infinity_mass = infinity_mass

  @classmethod
  def from_two_probability_mass_functions(
      cls,
      log_probability_mass_function_lower: typing.Mapping[typing.Any, float],
      log_probability_mass_function_upper: typing.Mapping[typing.Any, float],
      pessimistic_estimate: bool = True,
      value_discretization_interval: float = 1e-4,
      log_mass_truncation_bound: float = -math.inf
  ) -> 'PrivacyLossDistribution':
    """Constructs a privacy loss distribution from mu_lower and mu_upper.

    Args:
      log_probability_mass_function_lower: the probability mass function of
        mu_lower represented as a dictionary where each key is an outcome o of
        mu_lower and the corresponding value is the natural log of the
        probability mass of mu_lower at o.
      log_probability_mass_function_upper: the probability mass function of
        mu_upper represented as a dictionary where each key is an outcome o of
        mu_upper and the corresponding value is the natural log of the
        probability mass of mu_upper at o.
      pessimistic_estimate: whether the rounding is done in such a way that the
        resulting epsilon-hockey stick divergence computation gives an upper
        estimate to the real value.
      value_discretization_interval: the dicretization interval for the privacy
        loss distribution. The values will be rounded up/down to be an integer
        multiple of this number.
      log_mass_truncation_bound: when the log of the probability mass of the
        upper distribution is below this bound, it is either (i) included in
        infinity_mass in the case of pessimistic estimate or (ii) discarded
        completely in the case of optimistic estimate. The larger
        log_mass_truncation_bound is, the more error it may introduce in
        divergence calculations.

    Returns:
      The privacy loss distribution constructed as specified.
    """

    infinity_mass = 0
    for outcome in log_probability_mass_function_upper:
      if (log_probability_mass_function_lower.get(outcome,
                                                  -math.inf) == -math.inf):
        # When an outcome only appears in the upper distribution but not in the
        # lower distribution, then it must be counted in infinity_mass as such
        # an outcome contributes to the hockey stick divergence.
        infinity_mass += math.exp(log_probability_mass_function_upper[outcome])

    # Compute the (non-discretized) probability mass function for the privacy
    # loss distribution.
    probability_mass_function = {}
    for outcome in log_probability_mass_function_lower:
      if log_probability_mass_function_lower[outcome] == -math.inf:
        # This outcome never occurs in mu_lower. This case was already included
        # as infinity_mass above.
        continue
      elif (log_probability_mass_function_upper.get(outcome, -math.inf) >
            log_mass_truncation_bound):
        # When the probability mass of mu_upper at the outcome is greater than
        # the threshold, add it to the distribution.
        privacy_loss_value = (
            log_probability_mass_function_upper[outcome] -
            log_probability_mass_function_lower[outcome])
        probability_mass_function[privacy_loss_value] = (
            probability_mass_function.get(privacy_loss_value, 0) +
            math.exp(log_probability_mass_function_upper[outcome]))
      else:
        if pessimistic_estimate:
          # When the probability mass of mu_upper at the outcome is no more than
          # the threshold and we would like to get a pessimistic estimate,
          # account for this in infinity_mass.
          infinity_mass += math.exp(
              log_probability_mass_function_upper.get(outcome, -math.inf))

    # Discretize the probability mass so that the values are integer multiples
    # of value_discretization_interval
    rounded_probability_mass_function = collections.defaultdict(lambda: 0)
    round_fn = math.ceil if pessimistic_estimate else math.floor
    for val in probability_mass_function:
      rounded_probability_mass_function[
          round_fn(val / value_discretization_interval)
          ] += probability_mass_function[val]

    return cls(rounded_probability_mass_function, value_discretization_interval,
               infinity_mass)

  @classmethod
  def from_randomized_response(
      cls,
      noise_parameter: float,
      num_buckets: int,
      pessimistic_estimate: bool = True,
      value_discretization_interval: float = 1e-4) -> 'PrivacyLossDistribution':
    """Constructs the privacy loss distribution of Randomized Response.

    The Randomized Response over k buckets with noise parameter p takes in an
    input which is one of the k buckets. With probability 1 - p, it simply
    outputs the input bucket. Otherwise, with probability p, it outputs a bucket
    drawn uniformly at random from the k buckets.

    This function calculates the privacy loss distribution for the
    aforementioned Randomized Response with a given number of buckets, and a
    given noise parameter.

    Specifically, suppose that the original input is x and it is changed to x'.
    Recall that the privacy loss distribution of the Randomized Response
    mechanism is generated as follows: first pick o according to R(x), where
    R(x) denote the output distribution of the Randomized Response mechanism
    on input x. Then, the privacy loss is ln(Pr[R(x) = o] / Pr[R(x') = o]).
    There are three cases here:
      - When o = x, ln(Pr[R(x) = o] / Pr[R(x') = o]) =
        ln(Pr[R(x) = x] / Pr[R(x') = x]). Here Pr[R(x) = x] = 1 - p + p / k
        and Pr[R(x') = x] = p / k.
      - When o = x', ln(Pr[R(x) = o] / Pr[R(x') = o]) =
        ln(Pr[R(x') = x'] / Pr[R(x) = x']), which is just the negation of the
        previous privacy loss.
      - When o != x, x', the privacy loss is zero.

    Args:
      noise_parameter: the probability that the Randomized Response outputs a
        completely random bucket.
      num_buckets: the total number of possible input values (which is equal to
        the total number of possible output values).
      pessimistic_estimate: a value indicating whether the rounding is done in
        such a way that the resulting epsilon-hockey stick divergence
        computation gives an upper estimate to the real value.
      value_discretization_interval: the length of the dicretization interval
        for the privacy loss distribution. The values will be rounded up/down to
        be an integer multiple of this number.

    Returns:
      The privacy loss distribution constructed as specified.
    """

    if noise_parameter <= 0 or noise_parameter >= 1:
      raise ValueError(f'Noise parameter must be strictly between 0 and 1: '
                       f'{noise_parameter}')

    if num_buckets <= 1:
      raise ValueError(
          f'Number of buckets must be strictly greater than 1: {num_buckets}')

    round_fn = math.ceil if pessimistic_estimate else math.floor

    rounded_probability_mass_function = collections.defaultdict(lambda: 0)

    # Probability that the output is equal to the input, i.e., Pr[R(x) = x]
    probability_output_equal_input = ((1 - noise_parameter) +
                                      noise_parameter / num_buckets)
    # Probability that the output is equal to a specific bucket that is not the
    # input, i.e., Pr[R(x') = x] for x' != x.
    probability_output_not_input = noise_parameter / num_buckets

    # Add privacy loss for the case o = x
    rounded_value = round_fn(
        math.log(probability_output_equal_input / probability_output_not_input)
        / value_discretization_interval)
    rounded_probability_mass_function[
        rounded_value] += probability_output_equal_input

    # Add privacy loss for the case o = x'
    rounded_value = round_fn(
        math.log(probability_output_not_input / probability_output_equal_input)
        / value_discretization_interval)
    rounded_probability_mass_function[
        rounded_value] += probability_output_not_input

    # Add privacy loss for the case o != x, x'
    rounded_probability_mass_function[0] += (
        probability_output_not_input * (num_buckets - 2))

    return cls(rounded_probability_mass_function, value_discretization_interval,
               0)

  @classmethod
  def from_privacy_parameters(
      cls,
      privacy_parameters: DifferentialPrivacyParameters,
      value_discretization_interval: float = 1e-4) -> 'PrivacyLossDistribution':
    """Constructs pessimistic PLD from epsilon and delta parameters.

    When the mechanism is (epsilon, delta)-differentially private, the following
    is a pessimistic estimate of its privacy loss distribution (see Section 3.5
    of the supplementary material for more explanation):
      - infinity with probability delta.
      - epsilon with probability (1 - delta) / (1 + exp(-eps))
      - -epsilon with probability (1 - delta) / (1 + exp(eps))

    Args:
      privacy_parameters: the privacy guarantee of the mechanism.
      value_discretization_interval: the length of the dicretization interval
        for the privacy loss distribution. The values will be rounded up/down to
        be an integer multiple of this number.

    Returns:
      The privacy loss distribution constructed as specified.
    """
    delta = privacy_parameters.delta
    epsilon = privacy_parameters.epsilon

    rounded_probability_mass_function = {
        math.ceil(epsilon / value_discretization_interval):
            (1 - delta) / (1 + math.exp(-epsilon)),
        math.ceil(-epsilon / value_discretization_interval):
            (1 - delta) / (1 + math.exp(epsilon))
    }

    return cls(rounded_probability_mass_function, value_discretization_interval,
               privacy_parameters.delta)

  def get_delta_for_epsilon(self, epsilon: float) -> float:
    """Computes the epsilon-hockey stick divergence between mu_upper, mu_lower.

    When this privacy loss distribution corresponds to a mechanism, the
    epsilon-hockey stick divergence gives the value of delta for which the
    mechanism is (epsilon, delta)-differentially private. (See Observation 1 in
    the supplementary material.)

    Args:
      epsilon: the epsilon in epsilon-hockey stick divergence.

    Returns:
      A non-negative real number which is the epsilon-hockey stick divergence
      between the upper (mu_upper) and the lower (mu_lower) distributions
      corresponding to this privacy loss distribution.
    """

    # The epsilon-hockey stick divergence of mu_upper with respect to mu_lower
    # is  equal to (the sum over all the values in the privacy loss distribution
    # of the probability mass at value times max(0, 1 - e^{epsilon - value}) )
    # plus the infinity_mass.
    divergence = self.infinity_mass
    for i in self.rounded_probability_mass_function:
      val = i * self.value_discretization_interval
      if val > epsilon and self.rounded_probability_mass_function[i] > 0:
        divergence += ((1 - math.exp(epsilon - val)) *
                       self.rounded_probability_mass_function[i])

    return divergence

  def get_epsilon_for_delta(self, delta: float) -> float:
    """Computes epsilon for which hockey stick divergence is at most delta.

    This function computes the smallest non-negative epsilon for which the
    epsilon-hockey stick divergence between mu_upper, mu_lower is at most delta.

    When this privacy loss distribution corresponds to a mechanism and the
    rounding is pessimistic, the returned value corresponds to an epsilon for
    which the mechanism is (epsilon, delta)-differentially private. (See
    Observation 1 in the supplementary material.)

    Args:
      delta: the target epsilon-hockey stick divergence.

    Returns:
      A non-negative real number which is the smallest epsilon such that the
      epsilon-hockey stick divergence between the upper (mu_upper) and the
      lower (mu_lower) distributions is at most delta. When no such finite
      epsilon exists, return math.inf.
    """

    if self.infinity_mass > delta:
      return math.inf

    mass_upper = self.infinity_mass
    mass_lower = 0
    for i in sorted(
        self.rounded_probability_mass_function.keys(), reverse=True):
      val = i * self.value_discretization_interval

      if (mass_upper > delta and mass_lower > 0 and
          math.log((mass_upper - delta) / mass_lower) >= val):
        # Epsilon is greater than or equal to val.
        break

      mass_upper += self.rounded_probability_mass_function[i]
      mass_lower += (math.exp(-val) * self.rounded_probability_mass_function[i])

      if mass_upper >= delta and mass_lower == 0:
        # This only occurs when val is very large, which results in exp(-val)
        # being treated as zero.
        return max(0, val)

    if mass_upper <= mass_lower + delta:
      return 0
    else:
      return math.log((mass_upper - delta) / mass_lower)

  def compose(
      self, privacy_loss_distribution: 'PrivacyLossDistribution'
  ) -> 'PrivacyLossDistribution':
    """Computes a privacy loss distribution resulting from composing two PLDs.

    Args:
      privacy_loss_distribution: the privacy loss distribution to be composed
        with the current privacy loss distribution. The two must have the same
        value_discretization_interval.

    Returns:
      A privacy loss distribution which is the result of composing the two.
    """

    # The two privacy loss distributions must have the same discretization
    # interval for the composition to go through.
    if (self.value_discretization_interval !=
        privacy_loss_distribution.value_discretization_interval):
      raise ValueError(
          f'Discretization intervals are different: '
          f'{self.value_discretization_interval}'
          f'{privacy_loss_distribution.value_discretization_interval}')

    # The probability mass function of the resulting distribution is simply the
    # convolutaion of the two input probability mass functions.
    new_rounded_probability_mass_function = convolve_dictionary(
        self.rounded_probability_mass_function,
        privacy_loss_distribution.rounded_probability_mass_function)

    new_infinity_mass = (
        self.infinity_mass + privacy_loss_distribution.infinity_mass -
        (self.infinity_mass * privacy_loss_distribution.infinity_mass))

    return PrivacyLossDistribution(
        new_rounded_probability_mass_function,
        self.value_discretization_interval, new_infinity_mass)

  def self_compose(self, num_times: int) -> 'PrivacyLossDistribution':
    """Computes PLD resulting from repeated composing the PLD with itself.

    Args:
      num_times: the number of times to compose this PLD with itself.

    Returns:
      A privacy loss distribution which is the result of the composition.
    """

    new_rounded_probability_mass_function = self_convolve_dictionary(
        self.rounded_probability_mass_function, num_times)

    new_infinity_mass = (1 - ((1 - self.infinity_mass)**num_times))

    return PrivacyLossDistribution(new_rounded_probability_mass_function,
                                   self.value_discretization_interval,
                                   new_infinity_mass)


@dataclasses.dataclass
class TailPrivacyLossDistribution(object):
  """Representation of the tail of privacy loss distribution.

  Attributes:
    lower_x_truncation: the minimum value of x that should be considered after
      the tail is discarded.
    upper_x_truncation: the maximum value of x that should be considered after
      the tail is discarded.
    tail_probability_mass_function: the probability mass of the privacy loss
      distribution that has to be added due to the discarded tail; each key is a
      privacy loss value and the corresponding value is the probability mass
      that the value occurs.
  """
  lower_x_truncation: float
  upper_x_truncation: float
  tail_probability_mass_function: typing.Mapping[float, float]


class AdditiveNoisePrivacyLossDistribution(
    PrivacyLossDistribution, metaclass=abc.ABCMeta):
  """Superclass for privacy loss distributions of additive noise mechanisms.

  An additive noise mechanism for computing a scalar-valued function f is a
  mechanism that outputs the sum of the true value of the function and a noise
  drawn from a certain distribution mu. This class allows one to create and
  manipulate the privacy loss distribution (PLD) of additive noise mechanisms.

  We assume that the noise mu is such that the algorithm is more private as the
  sensitivity of f decreases. (Recall that the sensitivity of f is the maximum
  absolute change in f when an input to a single user changes.) Under this
  assumption, the PLD of the mechanism is exactly generated as follows: pick x
  from mu and let the privacy loss be ln(P(x) / P(x - sensitivity)). Note that
  when mu is discrete, P(x) and P(x - sensitivity) are the probability masses
  of mu at x and x - sensitivity respectively. When mu is continuous, P(x) and
  P(x - sensitivity) are the probability densities of mu at x and
  x - sensitivity respectively.

  Attributes:
    value_discretization_interval: the interval length for which the values of
      the privacy loss distribution are discretized. In particular, the values
      are always integer multiples of value_discretization_interval.
    rounded_probability_mass_function: the probability mass function for the
      privacy loss distribution where each value is rounded to be an integer
      multiple of value_discretization_interval. To avoid floating point errors
      in the values, the keys here are the integer multipliers. For example,
      suppose that the probability mass function assigns mass of 0.1 to the
      value 2 * value_discretization_interval, then the dictionary will have
      (key: value) pair (2: 0.1).
    infinity_mass: the probability mass of mu over all the outcomes that can
      occur only in mu but not in mu shifted by the sensitivity.
  """

  def __init__(self,
               sensitivity: float = 1,
               pessimistic_estimate: bool = True,
               value_discretization_interval: float = 1e-4,
               discrete_noise: bool = False) -> None:
    """Initializes the privacy loss distribution of an additive noise mechanism.

    This function assumes the privacy loss is non-increasing as x increases.

    Args:
      sensitivity: the sensitivity of function f. (i.e. the maximum absolute
        change in f when an input to a single user changes.)
      pessimistic_estimate: a value indicating whether the rounding is done in
        such a way that the resulting epsilon-hockey stick divergence
        computation gives an upper estimate to the real value.
      value_discretization_interval: the length of the dicretization interval
        for the privacy loss distribution. The values will be rounded up/down to
        be an integer multiple of this number.
      discrete_noise: a value indicating whether the noise is discrete. If this
        is True, then it is assumed that the noise can only take integer values.
        If False, then it is assumed that the noise is continuous, i.e., the
        probability mass at any given point is zero.
    """
    if sensitivity <= 0:
      raise ValueError(
          f'Sensitivity is not a positive real number: {sensitivity}')
    self._sensitivity = sensitivity

    round_fn = math.ceil if pessimistic_estimate else math.floor

    tail_pld = self.privacy_loss_tail()

    rounded_probability_mass_function = collections.defaultdict(lambda: 0)
    infinity_mass = tail_pld.tail_probability_mass_function.get(math.inf, 0)
    for privacy_loss in tail_pld.tail_probability_mass_function:
      if privacy_loss != math.inf:
        rounded_probability_mass_function[round_fn(
            privacy_loss / value_discretization_interval
        )] += tail_pld.tail_probability_mass_function[privacy_loss]

    if discrete_noise:
      for x in range(
          math.ceil(tail_pld.lower_x_truncation),
          math.floor(tail_pld.upper_x_truncation) + 1):
        rounded_probability_mass_function[round_fn(self.privacy_loss(x))] += (
            self.noise_cdf(x) - self.noise_cdf(x - 1))
    else:
      lower_x = tail_pld.lower_x_truncation
      rounded_down_value = math.floor(
          self.privacy_loss(lower_x) / value_discretization_interval)
      while lower_x < tail_pld.upper_x_truncation:
        upper_x = min(
            tail_pld.upper_x_truncation,
            self.inverse_privacy_loss(value_discretization_interval *
                                      rounded_down_value))

        # Each x in [lower_x, upper_x] results in privacy loss that lies in
        # [value_discretization_interval * rounded_down_value,
        #  value_discretization_interval * (rounded_down_value + 1)]
        probability_mass = self.noise_cdf(upper_x) - self.noise_cdf(lower_x)
        rounded_value = round_fn(rounded_down_value + 0.5)
        rounded_probability_mass_function[rounded_value] += probability_mass

        lower_x = upper_x
        rounded_down_value -= 1

    super(AdditiveNoisePrivacyLossDistribution, self).__init__(
        dict(rounded_probability_mass_function), value_discretization_interval,
        infinity_mass)

  def get_delta_for_epsilon(self, epsilon):
    """Computes the epsilon-hockey stick divergence of the mechanism.

    The epsilon-hockey stick divergence of the mechanism is the value of delta
    for which the mechanism is (epsilon, delta)-differentially private. (See
    Observation 1 in the supplementary material.)

    This function assumes the privacy loss is non-increasing as x increases.
    Under this assumption, the hockey stick divergence is simply
    CDF(inverse_privacy_loss(epsilon)) - exp(epsilon) *
    CDF(inverse_privacy_loss(epsilon) - sensitivity), because the privacy loss
    at a point x is at least epsilon iff x <= inverse_privacy_loss(epsilon).

    Args:
      epsilon: the epsilon in epsilon-hockey stick divergence.

    Returns:
      A non-negative real number which is the epsilon-hockey stick divergence
      of the mechanism.
    """
    x_cutoff = self.inverse_privacy_loss(epsilon)
    return self.noise_cdf(x_cutoff) - math.exp(epsilon) * self.noise_cdf(
        x_cutoff - self._sensitivity)

  @abc.abstractmethod
  def privacy_loss_tail(self) -> TailPrivacyLossDistribution:
    """Computes the privacy loss at the tail of the distribution.

    Returns:
      A TailPrivacyLossDistribution instance representing the tail of the
      privacy loss distribution.

    Raises:
      NotImplementedError: If not implemented by the subclass.
    """
    raise NotImplementedError

  @abc.abstractmethod
  def privacy_loss(self, x: float) -> float:
    """Computes the privacy loss at a given point.

    Args:
      x: the point at which the privacy loss is computed.

    Returns:
      The privacy loss at point x, which is equal to
      ln(P(x) / P(x - sensitivity)).

    Raises:
      NotImplementedError: If not implemented by the subclass.
    """
    raise NotImplementedError

  @abc.abstractmethod
  def inverse_privacy_loss(self, privacy_loss: float) -> float:
    """Computes the inverse of a given privacy loss.

    Args:
      privacy_loss: the privacy loss value.

    Returns:
      The largest float x such that the privacy loss at x is at least
      privacy_loss.

    Raises:
      NotImplementedError: If not implemented by the subclass.
    """
    raise NotImplementedError

  @abc.abstractmethod
  def noise_cdf(self, x: float) -> float:
    """Computes the cumulative density function of the noise distribution.

    Args:
      x: the point at which the cumulative density function is to be calculated.

    Returns:
      The cumulative density function of that noise at x, i.e., the probability
      that mu is less than or equal to x.

    Raises:
      NotImplementedError: If not implemented by the subclass.
    """
    raise NotImplementedError

  @classmethod
  @abc.abstractmethod
  def from_privacy_guarantee(
      cls,
      privacy_parameters: DifferentialPrivacyParameters,
      sensitivity: float = 1,
      pessimistic_estimate: bool = True,
      value_discretization_interval: float = 1e-4
  ) -> 'AdditiveNoisePrivacyLossDistribution':
    """Creates the PLD for the mechanism with a desired privacy guarantee.

    Args:
      privacy_parameters: the desired privacy guarantee of the mechanism.
      sensitivity: the sensitivity of function f. (i.e. the maximum absolute
        change in f when an input to a single user changes.)
      pessimistic_estimate: a value indicating whether the rounding is done in
        such a way that the resulting epsilon-hockey stick divergence
        computation gives an upper estimate to the real value.
      value_discretization_interval: the length of the dicretization interval
        for the privacy loss distribution. The values will be rounded up/down to
        be an integer multiple of this number.

    Returns:
      The privacy loss distribution of the mechanism with the given privacy
        guarantee.

    Raises:
      NotImplementedError: If not implemented by the subclass.
    """
    raise NotImplementedError


class LaplacePrivacyLossDistribution(AdditiveNoisePrivacyLossDistribution):
  """Privacy loss distribution of the Laplace mechanism.

  The Laplace mechanism for computing a scalar-valued function f simply outputs
  the sum of the true value of the function and a noise drawn from the Laplace
  distribution. Recall that the Laplace distribution with parameter b has
  probability density function 0.5/b * exp(-|x|/b) at x for any real number x.

  This function calculates the privacy loss distribution for the aforementioned
  Laplace mechanism with a given parameter, and a given sensitivity of the
  function f. This is equivalent to the privacy loss distribution between the
  Laplace distribution and the same distribution but shifted by the sensitivity.
  More specifically, the privacy loss distribution of the Laplace mechanism is
  generated as follows: first pick x according to the Laplace noise. Then, let
  the privacy loss be ln(PDF(x) / PDF(x - sensitivity)) which is equal to
  (|x - sensitivity| - |x|) / parameter.

  Attributes:
    value_discretization_interval: the interval length for which the values of
      the privacy loss distribution are discretized. In particular, the values
      are always integer multiples of value_discretization_interval.
    rounded_probability_mass_function: the probability mass function for the
      privacy loss distribution where each value is rounded to be an integer
      multiple of value_discretization_interval. To avoid floating point errors
      in the values, the keys here are the integer multipliers. For example,
      suppose that the probability mass function assigns mass of 0.1 to the
      value 2 * value_discretization_interval, then the dictionary will have
      (key: value) pair (2: 0.1).
  """

  def __init__(self,
               parameter: float,
               sensitivity: float = 1,
               pessimistic_estimate: bool = True,
               value_discretization_interval: float = 1e-4) -> None:
    """Initializes the privacy loss distribution of the Laplace mechanism.

    Args:
      parameter: the parameter of the Laplace distribution.
      sensitivity: the sensitivity of function f. (i.e. the maximum absolute
        change in f when an input to a single user changes.)
      pessimistic_estimate: a value indicating whether the rounding is done in
        such a way that the resulting epsilon-hockey stick divergence
        computation gives an upper estimate to the real value.
      value_discretization_interval: the length of the dicretization interval
        for the privacy loss distribution. The values will be rounded up/down to
        be an integer multiple of this number.
    """
    if parameter <= 0:
      raise ValueError(f'Parameter is not a positive real number: {parameter}')

    self._parameter = parameter
    self._laplace_random_variable = stats.laplace(scale=parameter)

    super(LaplacePrivacyLossDistribution,
          self).__init__(sensitivity, pessimistic_estimate,
                         value_discretization_interval)

  def privacy_loss_tail(self) -> TailPrivacyLossDistribution:
    """Computes the privacy loss at the tail of the Laplace distribution.

    When x <= 0, the privacy loss is simply sensitivity / parameter; this
    happens with probability 0.5. When x >= sensitivity, the privacy loss is
    simply - sensitivity / parameter; this happens with probability
    1 - CDF(sensitivity) = CDF(-sensitivity).

    Returns:
      A TailPrivacyLossDistribution instance representing the tail of the
      privacy loss distribution.
    """
    return TailPrivacyLossDistribution(
        0.0, self._sensitivity, {
            self._sensitivity / self._parameter:
                0.5,
            -self._sensitivity / self._parameter:
                self._laplace_random_variable.cdf(-self._sensitivity)
        })

  def privacy_loss(self, x: float) -> float:
    """Computes the privacy loss of the Laplace mechanism at a given point.

    Args:
      x: the point at which the privacy loss is computed.

    Returns:
      The privacy loss of the Laplace mechanism at point x, which is equal to
      (|x - sensitivity| - |x|) / parameter.
    """
    return (abs(x - self._sensitivity) - abs(x)) / self._parameter

  def inverse_privacy_loss(self, privacy_loss: float) -> float:
    """Computes the inverse of a given privacy loss for the Laplace mechanism.

    Args:
      privacy_loss: the privacy loss value.

    Returns:
      The largest float x such that the privacy loss at x is at least
      privacy_loss. When privacy_loss is at most - sensitivity / parameter, x is
      equal to infinity. When - sensitivity / parameter < privacy_loss <=
      sensitivity / parameter, x is equal to
      0.5 * (sensitivity - privacy_loss * parameter). When privacy_loss >
      sensitivity / parameter, no such x exists and the function returns
      -infinity.
    """
    if privacy_loss > self._sensitivity / self._parameter:
      return -math.inf
    if privacy_loss <= -self._sensitivity / self._parameter:
      return math.inf
    return 0.5 * (self._sensitivity - privacy_loss * self._parameter)

  def noise_cdf(self, x: float) -> float:
    """Computes the cumulative density function of the Laplace distribution.

    Args:
      x: the point at which the cumulative density function is to be calculated.

    Returns:
      The cumulative density function of the Laplace noise at x, i.e., the
      probability that the Laplace noise is less than or equal to x.
    """
    return self._laplace_random_variable.cdf(x)

  @classmethod
  def from_privacy_guarantee(
      cls,
      privacy_parameters: DifferentialPrivacyParameters,
      sensitivity: float = 1,
      pessimistic_estimate: bool = True,
      value_discretization_interval: float = 1e-4
  ) -> 'LaplacePrivacyLossDistribution':
    """Creates the PLD for Laplace mechanism with a desired privacy guarantee.

    The parameter of the Laplace mechanism is simply sensitivity / epsilon.

    Args:
      privacy_parameters: the desired privacy guarantee of the mechanism.
      sensitivity: the sensitivity of function f. (i.e. the maximum absolute
        change in f when an input to a single user changes.)
      pessimistic_estimate: a value indicating whether the rounding is done in
        such a way that the resulting epsilon-hockey stick divergence
        computation gives an upper estimate to the real value.
      value_discretization_interval: the length of the dicretization interval
        for the privacy loss distribution. The values will be rounded up/down to
        be an integer multiple of this number.

    Returns:
      The privacy loss distribution of the Laplace mechanism with the given
        privacy guarantee.
    """
    parameter = sensitivity / privacy_parameters.epsilon
    return LaplacePrivacyLossDistribution(
        parameter,
        sensitivity=sensitivity,
        pessimistic_estimate=pessimistic_estimate,
        value_discretization_interval=value_discretization_interval)


class GaussianPrivacyLossDistribution(AdditiveNoisePrivacyLossDistribution):
  """Privacy loss distribution of the Gaussian mechanism.

  The Gaussian mechanism for computing a scalar-valued function f simply
  outputs the sum of the true value of the function and a noise drawn from the
  Gaussian distribution. Recall that the (centered) Gaussian distribution with
  standard deviation sigma has probability density function
  1/(sigma * sqrt(2 * pi)) * exp(-0.5 x^2/sigma^2) at x for any real number x.

  This function calculates the privacy loss distribution for the
  aforementioned Gaussian mechanism with a given standard deviation, and a
  given sensitivity of the function f. This is equivalent to the privacy loss
  distribution between the Gaussian distribution and the same distribution but
  shifted by the sensitivity. More specifically, the privacy loss distribution
  of the Gaussian mechanism is generated as follows: first pick x according to
  the Gaussian noise. Then, let the privacy loss be
  ln(PDF(x) / PDF(x - sensitivity)) which is equal to
  0.5 * sensitivity * (sensitivity - 2 * x) / sigma^2.

  Attributes:
    value_discretization_interval: the interval length for which the values of
      the privacy loss distribution are discretized. In particular, the values
      are always integer multiples of value_discretization_interval.
    rounded_probability_mass_function: the probability mass function for the
      privacy loss distribution where each value is rounded to be an integer
      multiple of value_discretization_interval. To avoid floating point errors
      in the values, the keys here are the integer multipliers. For example,
      suppose that the probability mass function assigns mass of 0.1 to the
      value 2 * value_discretization_interval, then the dictionary will have
      (key: value) pair (2: 0.1).
  """

  def __init__(self,
               standard_deviation: float,
               sensitivity: float = 1,
               pessimistic_estimate: bool = True,
               value_discretization_interval: float = 1e-4,
               log_mass_truncation_bound: float = -50) -> None:
    """Initializes the privacy loss distribution of the Gaussian mechanism.

    Args:
      standard_deviation: the standard_deviation of the Gaussian distribution.
      sensitivity: the sensitivity of function f. (i.e. the maximum absolute
        change in f when an input to a single user changes.)
      pessimistic_estimate: a value indicating whether the rounding is done in
        such a way that the resulting epsilon-hockey stick divergence
        computation gives an upper estimate to the real value.
      value_discretization_interval: the length of the dicretization interval
        for the privacy loss distribution. The values will be rounded up/down to
        be an integer multiple of this number.
      log_mass_truncation_bound: the ln of the probability mass that might be
        discarded from the noise distribution. The larger this number, the more
        error it may introduce in divergence calculations.
    """
    if standard_deviation <= 0:
      raise ValueError(f'Standard deviation is not a positive real number: '
                       f'{standard_deviation}')

    self._standard_deviation = standard_deviation
    self._gaussian_random_variable = stats.norm(scale=standard_deviation)
    self._pessimistic_estimate = pessimistic_estimate
    self._log_mass_truncation_bound = log_mass_truncation_bound

    super(GaussianPrivacyLossDistribution,
          self).__init__(sensitivity, pessimistic_estimate,
                         value_discretization_interval)

  def privacy_loss_tail(self) -> TailPrivacyLossDistribution:
    """Computes the privacy loss at the tail of the Gaussian distribution.

    We set lower_x_truncation so that CDF(lower_x_truncation) =
    0.5 * exp(log_mass_truncation_bound), and then set upper_x_truncation to be
    -lower_x_truncation.

    If pessimistic_estimate is True, the privacy losses for
    x < lower_x_truncation and x > upper_x_truncation are rounded up and added
    to tail_probability_mass_function. In the case x < lower_x_truncation,
    the privacy loss is rounded up to infinity. In the case
    x > upper_x_truncation, it is rounded up to the privacy loss at
    upper_x_truncation.

    On the other hand, if pessimistic_estimate is False, the privacy losses for
    x < lower_x_truncation and x > upper_x_truncation are rounded down and added
    to tail_probability_mass_function. In the case x < lower_x_truncation, the
    privacy loss is rounded down to the privacy loss at lower_x_truncation.
    In the case x > upper_x_truncation, it is rounded down to -infinity and
    hence not included in tail_probability_mass_function,

    Returns:
      A TailPrivacyLossDistribution instance representing the tail of the
      privacy loss distribution.
    """
    lower_x_truncation = self._gaussian_random_variable.ppf(
        0.5 * math.exp(self._log_mass_truncation_bound))
    upper_x_truncation = -lower_x_truncation
    if self._pessimistic_estimate:
      tail_probability_mass_function = {
          math.inf:
              0.5 * math.exp(self._log_mass_truncation_bound),
          self.privacy_loss(upper_x_truncation):
              0.5 * math.exp(self._log_mass_truncation_bound)
      }
    else:
      tail_probability_mass_function = {
          self.privacy_loss(lower_x_truncation):
              0.5 * math.exp(self._log_mass_truncation_bound),
      }
    return TailPrivacyLossDistribution(lower_x_truncation, upper_x_truncation,
                                       tail_probability_mass_function)

  def privacy_loss(self, x: float) -> float:
    """Computes the privacy loss of the Gaussian mechanism at a given point.

    Args:
      x: the point at which the privacy loss is computed.

    Returns:
      The privacy loss of the Gaussian mechanism at point x, which is equal to
      0.5 * sensitivity * (sensitivity - 2 * x) / standard_deviation^2.
    """
    return (0.5 * self._sensitivity * (self._sensitivity - 2 * x) /
            (self._standard_deviation**2))

  def inverse_privacy_loss(self, privacy_loss: float) -> float:
    """Computes the inverse of a given privacy loss for the Gaussian mechanism.

    Args:
      privacy_loss: the privacy loss value.

    Returns:
      The largest float x such that the privacy loss at x is at least
      privacy_loss. This is equal to
      0.5 * sensitivity - privacy_loss * standard_deviation^2 / sensitivity.
    """
    return (0.5 * self._sensitivity - privacy_loss *
            (self._standard_deviation**2) / self._sensitivity)

  def noise_cdf(self, x: float) -> float:
    """Computes the cumulative density function of the Gaussian distribution.

    Args:
      x: the point at which the cumulative density function is to be calculated.

    Returns:
      The cumulative density function of the Gaussian noise at x, i.e., the
      probability that the Gaussian noise is less than or equal to x.
    """
    return self._gaussian_random_variable.cdf(x)

  @classmethod
  def from_privacy_guarantee(
      cls,
      privacy_parameters: DifferentialPrivacyParameters,
      sensitivity: float = 1,
      pessimistic_estimate: bool = True,
      value_discretization_interval: float = 1e-4
  ) -> 'GaussianPrivacyLossDistribution':
    """Creates the PLD for Gaussian mechanism with a desired privacy guarantee.

    Use binary search to find the smallest possible standard deviation of the
    Gaussian noise for which the protocol is (epsilon, delta)-differentially
    private.

    Args:
      privacy_parameters: the desired privacy guarantee of the mechanism.
      sensitivity: the sensitivity of function f. (i.e. the maximum absolute
        change in f when an input to a single user changes.)
      pessimistic_estimate: a value indicating whether the rounding is done in
        such a way that the resulting epsilon-hockey stick divergence
        computation gives an upper estimate to the real value.
      value_discretization_interval: the length of the dicretization interval
        for the privacy loss distribution. The values will be rounded up/down to
        be an integer multiple of this number.

    Returns:
      The privacy loss distribution of the Gaussian mechanism with the given
        privacy guarantee.
    """
    # The initial standard deviation is set to
    # sqrt(2 * ln(1.5/delta) * sensitivity / epsilon. It is known that, when
    # epsilon is no more than one, the Gaussian mechanism with this standard
    # deviation is (epsilon, delta)-DP. See e.g. Appendix A in Dwork and Roth
    # book, "The Algorithmic Foundations of Differential Privacy".
    initial_standard_deviation = math.sqrt(
        2 * math.log(1.5 / privacy_parameters.delta)
    ) * sensitivity / privacy_parameters.epsilon

    # When epsilon > 1, it can be the case that the above standard deviation is
    # not sufficient to guarantee (eps, delta)-DP. Below we repeatedly doubling
    # the standard deviation until the mechanism is (eps, delta)-DP.
    upper_standard_deviation = initial_standard_deviation
    while GaussianPrivacyLossDistribution(
        upper_standard_deviation,
        sensitivity=sensitivity,
        log_mass_truncation_bound=0).get_delta_for_epsilon(
            privacy_parameters.epsilon) > privacy_parameters.delta:
      upper_standard_deviation *= 2

    lower_standard_deviation = 0

    while upper_standard_deviation - lower_standard_deviation > 1e-7:
      mid_standard_deviation = (upper_standard_deviation +
                                lower_standard_deviation) / 2
      if GaussianPrivacyLossDistribution(
          mid_standard_deviation,
          sensitivity=sensitivity,
          log_mass_truncation_bound=0).get_delta_for_epsilon(
              privacy_parameters.epsilon) <= privacy_parameters.delta:
        upper_standard_deviation = mid_standard_deviation
      else:
        lower_standard_deviation = mid_standard_deviation

    return GaussianPrivacyLossDistribution(
        upper_standard_deviation,
        sensitivity=sensitivity,
        pessimistic_estimate=pessimistic_estimate,
        value_discretization_interval=value_discretization_interval)

  @property
  def standard_deviation(self) -> float:
    """The standard deviation of the noise associated with this PLD."""
    return self._standard_deviation

  def self_compose(self, num_times: int) -> 'GaussianPrivacyLossDistribution':
    """Computes PLD resulting from repeated composing the PLD with itself.

    The composition of a Gaussian PLD with itself k times is the same as the PLD
    of the Gaussian Mechanism with sensitivity scaled up by a factor of square
    root of k.

    Args:
      num_times: the number of times to compose this PLD with itself.

    Returns:
      A privacy loss distribution which is the result of the composition.
    """
    return GaussianPrivacyLossDistribution(
        self._standard_deviation,
        sensitivity=self._sensitivity * math.sqrt(num_times),
        pessimistic_estimate=self._pessimistic_estimate,
        value_discretization_interval=self.value_discretization_interval)


class DiscreteLaplacePrivacyLossDistribution(
    AdditiveNoisePrivacyLossDistribution):
  """Privacy loss distribution of the discrete Laplace mechanism.

  The discrete Laplace mechanism for computing an integer-valued function f
  simply outputs the sum of the true value of the function and a noise drawn
  from the discrete Laplace distribution. Recall that the discrete Laplace
  distribution with parameter a > 0 has probability mass function
  Z * exp(-a * |x|) at x for any integer x, where Z = (e^a - 1) / (e^a + 1).

  This class represents the privacy loss distribution for the aforementioned
  discrete Laplace mechanism with a given parameter, and a given sensitivity of
  the function f. It is assumed that the function f only outputs an integer.
  This privacy loss distribution is equivalent to that between the discrete
  Laplace distribution and the same distribution but shifted by the sensitivity.
  More specifically, the privacy loss distribution of the discrete Laplace
  mechanism is generated as follows: first pick x according to the discrete
  Laplace noise. Then, let the privacy loss be ln(PMF(x) / PMF(x - sensitivity))
  which is equal to parameter * (|x - sensitivity| - |x|).

  Attributes:
    value_discretization_interval: the interval length for which the values of
      the privacy loss distribution are discretized. In particular, the values
      are always integer multiples of value_discretization_interval.
    rounded_probability_mass_function: the probability mass function for the
      privacy loss distribution where each value is rounded to be an integer
      multiple of value_discretization_interval. To avoid floating point errors
      in the values, the keys here are the integer multipliers. For example,
      suppose that the probability mass function assigns mass of 0.1 to the
      value 2 * value_discretization_interval, then the dictionary will have
      (key: value) pair (2: 0.1).
  """

  def __init__(self,
               parameter: float,
               sensitivity: int = 1,
               pessimistic_estimate: bool = True,
               value_discretization_interval: float = 1e-4) -> None:
    """Initializes the privacy loss distribution of the Laplace mechanism.

    Args:
      parameter: the parameter of the discrete Laplace distribution.
      sensitivity: the sensitivity of function f. (i.e. the maximum absolute
        change in f when an input to a single user changes.)
      pessimistic_estimate: a value indicating whether the rounding is done in
        such a way that the resulting epsilon-hockey stick divergence
        computation gives an upper estimate to the real value.
      value_discretization_interval: the length of the dicretization interval
        for the privacy loss distribution. The values will be rounded up/down to
        be an integer multiple of this number.
    """
    if parameter <= 0:
      raise ValueError(f'Parameter is not a positive real number: {parameter}')

    if not isinstance(sensitivity, int):
      raise ValueError(
          f'Sensitivity of the discrete Laplace mechanism must be an integer : '
          f'{sensitivity}')

    self._parameter = parameter
    self._discrete_laplace_random_variable = stats.dlaplace(parameter)

    super(DiscreteLaplacePrivacyLossDistribution, self).__init__(
        sensitivity,
        pessimistic_estimate,
        value_discretization_interval,
        discrete_noise=True)

  def privacy_loss_tail(self) -> TailPrivacyLossDistribution:
    """Computes privacy loss at the tail of the discrete Laplace distribution.

    When x <= 0, the privacy loss is simply sensitivity * parameter; this
    happens with probability CDF(0). When x >= sensitivity, the privacy loss is
    simply - sensitivity * parameter; this happens with probability
    1 - CDF(sensitivity - 1) = CDF(-sensitivity).

    Returns:
      A TailPrivacyLossDistribution instance representing the tail of the
      privacy loss distribution.
    """
    return TailPrivacyLossDistribution(
        1, self._sensitivity - 1, {
            self._sensitivity * self._parameter:
                self._discrete_laplace_random_variable.cdf(0),
            -self._sensitivity * self._parameter:
                self._discrete_laplace_random_variable.cdf(-self._sensitivity)
        })

  def privacy_loss(self, x: float) -> float:
    """Computes privacy loss of the discrete Laplace mechanism at a given point.

    Args:
      x: the point at which the privacy loss is computed.

    Returns:
      The privacy loss of the discrete Laplace mechanism at point x, which is
      equal to (|x - sensitivity| - |x|) * parameter for any integer x.
    """
    if not isinstance(x, int):
      raise ValueError(f'Privacy loss at x is undefined for x = {x}')

    return (abs(x - self._sensitivity) - abs(x)) * self._parameter

  def inverse_privacy_loss(self, privacy_loss: float) -> float:
    """Computes the inverse of a given privacy loss for the Laplace mechanism.

    Args:
      privacy_loss: the privacy loss value.

    Returns:
      The largest float x such that the privacy loss at x is at least
      privacy_loss. When privacy_loss is at most - sensitivity * parameter, x is
      equal to infinity. When - sensitivity * parameter < privacy_loss <=
      sensitivity * parameter, x is equal to
      floor(0.5 * (sensitivity - privacy_loss / parameter)). When privacy_loss >
      sensitivity * parameter, no such x exists and the function returns
      -infinity.
    """
    if privacy_loss > self._sensitivity * self._parameter:
      return -math.inf
    if privacy_loss <= -self._sensitivity * self._parameter:
      return math.inf
    return math.floor(0.5 *
                      (self._sensitivity - privacy_loss / self._parameter))

  def noise_cdf(self, x: float) -> float:
    """Computes cumulative density function of the discrete Laplace distribution.

    Args:
      x: the point at which the cumulative density function is to be calculated.

    Returns:
      The cumulative density function of the discrete Laplace noise at x, i.e.,
      the probability that the discrete Laplace noise is less than or equal to
      x.
    """
    return self._discrete_laplace_random_variable.cdf(x)

  @classmethod
  def from_privacy_guarantee(
      cls,
      privacy_parameters: DifferentialPrivacyParameters,
      sensitivity: float = 1,
      pessimistic_estimate: bool = True,
      value_discretization_interval: float = 1e-4
  ) -> 'DiscreteLaplacePrivacyLossDistribution':
    """Creates the PLD for discrete Laplace mechanism with desired privacy.

    The parameter of the discrete Laplace mechanism is simply
    epsilon / sensitivity.

    Args:
      privacy_parameters: the desired privacy guarantee of the mechanism.
      sensitivity: the sensitivity of function f. (i.e. the maximum absolute
        change in f when an input to a single user changes.)
      pessimistic_estimate: a value indicating whether the rounding is done in
        such a way that the resulting epsilon-hockey stick divergence
        computation gives an upper estimate to the real value.
      value_discretization_interval: the length of the dicretization interval
        for the privacy loss distribution. The values will be rounded up/down to
        be an integer multiple of this number.

    Returns:
      The privacy loss distribution of the discrete Laplace mechanism with the
        given privacy guarantee.
    """

    return DiscreteLaplacePrivacyLossDistribution(
        privacy_parameters.epsilon / sensitivity,
        sensitivity=math.ceil(sensitivity),
        pessimistic_estimate=pessimistic_estimate,
        value_discretization_interval=value_discretization_interval)
