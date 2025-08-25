using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class ExplosionBehavior : MonoBehaviour
{
	public ParticleSystem emit;
    // Start is called before the first frame update
    void Start(){
        GetComponent<Animator>().SetInteger("ExplosionNumber", Random.Range(1, 4));
    }

    // Update is called once per frame
    void Update()
    {
        
    }
	
	public void destroy(){
		// This splits the particle off so it doesn't get deleted with the parent
        emit.transform.parent = null;
        // this stops the particle from creating more bits
		var emission = emit.emission;
        emission.rateOverTime = 0;
		//This destroys the projectile
		Destroy (gameObject);
	}
}
