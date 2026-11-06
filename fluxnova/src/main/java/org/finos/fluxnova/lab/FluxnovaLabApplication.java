package org.finos.fluxnova.lab;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Fluxnova engine with REST API and web apps. The sample process and decision
 * under src/main/resources/processes are deployed automatically at startup.
 */
@SpringBootApplication
public class FluxnovaLabApplication {

  public static void main(String... args) {
    SpringApplication.run(FluxnovaLabApplication.class, args);
  }
}
